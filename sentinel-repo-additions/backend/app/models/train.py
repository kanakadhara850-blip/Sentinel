"""Model training with time-aware splits, imbalance-aware metrics, weight calibration and versioned artifacts.
Usage: python -m app.models.train --n 20000
Leakage controls: chronological 70/15/15 split (never shuffled); features built only from past state; labels never enter events;
Isolation Forest fits on training-period legitimate traffic only; early stopping uses the validation block, metrics use the untouched test block."""
import argparse
import itertools
import json
import math
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score)

from app.common.util import to_epoch
from app.config import settings
from app.features.feature_store import FEATURE_NAMES, MemoryFeatureStore
from app.risk.risk_engine import RiskEngine
from app.rules.rule_engine import RuleEngine
from app.simulation.generator import TxnGenerator


def build_dataset(n, seed, policy):
    fs, rules = MemoryFeatureStore(policy["velocity"]), RuleEngine(policy, settings.PSEUDONYM_KEY)
    prefixes = tuple(policy["lists"]["suspicious_ip_prefixes"])
    rows = []
    for i, (ev, y) in enumerate(TxnGenerator(seed=seed).stream(n)):
        e = {**ev, "event_id": str(i), "ts": to_epoch(ev["event_time"]), "ip_suspicious": int(ev["ip_address"].startswith(prefixes))}
        f = fs.update_and_get(e)
        rows.append({**f, "ip_suspicious": e["ip_suspicious"], "rule_score": rules.evaluate(e, f).score, "ts": e["ts"], "label": y})
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)


def metrics(y, score, thr=0.5):
    pred = (score >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"precision": float(precision_score(y, pred, zero_division=0)), "recall": float(recall_score(y, pred, zero_division=0)),
            "f1": float(f1_score(y, pred, zero_division=0)), "roc_auc": float(roc_auc_score(y, score)),
            "pr_auc": float(average_precision_score(y, score)), "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
            "threshold": thr, "positives": int(y.sum()), "n": int(len(y))}


def components(df, anomaly, scam):
    return (anomaly, scam, df["amount_ratio"].map(RiskEngine.amount_norm).values, df["velocity_score"].values, df["rule_score"].values)


def calibrate_weights(engine, comps, y):
    """Grid-search risk weights on the VALIDATION block, maximising PR-AUC of the final 0-100 score."""
    best = (-1, None)
    for w_ml, w_a, w_v, share in itertools.product([.4, .5, .6, .7, .8], [.05, .1, .15, .2], [.05, .1, .15, .2], [.2, .3, .4]):
        w_r = round(1 - w_ml - w_a - w_v, 4)
        if w_r < .05:
            continue
        w = {"w_ml": w_ml, "w_amount": w_a, "w_velocity": w_v, "w_rule": w_r, "anomaly_share": share}
        engine.set_weights(w)
        ap = average_precision_score(y, engine.score(*comps))
        if ap > best[0]:
            best = (ap, w)
    return best[1], best[0]


def train(n=20000, seed=7, artifact_dir=None, extra: pd.DataFrame = None, policy=None, quiet=False):
    policy, artifact_dir = policy or settings.load_policy(), Path(artifact_dir or settings.ARTIFACT_DIR)
    df = build_dataset(n, seed, policy)
    a, b = int(len(df) * .70), int(len(df) * .85)
    tr, va, te = df.iloc[:a], df.iloc[a:b], df.iloc[b:]
    if extra is not None and len(extra):                               # analyst-confirmed labels join the TRAIN block only
        tr = pd.concat([tr, extra[FEATURE_NAMES + ["label"]]], ignore_index=True)
    X = lambda d: d[FEATURE_NAMES].values.astype(float)

    iso = IsolationForest(n_estimators=200, contamination="auto", random_state=seed, n_jobs=1).fit(X(tr[tr.label == 0]))
    s_tr = -iso.score_samples(X(tr[tr.label == 0]))
    norm = {"lo": float(np.percentile(s_tr, 50)), "hi": float(np.percentile(s_tr, 99))}
    an = lambda d: np.clip((-iso.score_samples(X(d)) - norm["lo"]) / (norm["hi"] - norm["lo"]), 0, 1)

    pos = max(1, int(tr.label.sum()))
    clf = xgb.XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.08, subsample=.9, colsample_bytree=.9, n_jobs=1,
                            scale_pos_weight=math.sqrt((len(tr) - pos) / pos), eval_metric="aucpr", early_stopping_rounds=20, random_state=seed)
    clf.fit(X(tr), tr.label.values, eval_set=[(X(va), va.label.values)], verbose=False)

    engine = RiskEngine(policy)
    cv, ct = components(va, an(va), clf.predict_proba(X(va))[:, 1]), components(te, an(te), clf.predict_proba(X(te))[:, 1])
    weights, val_ap = calibrate_weights(engine, cv, va.label.values)
    engine.set_weights(weights)
    risk_te = engine.score(*ct)
    sens = [{"threshold": t, **{k: v for k, v in metrics(te.label.values, risk_te, t).items() if k in ("precision", "recall", "f1")}} for t in range(20, 95, 5)]
    m = {"IsolationForest": metrics(te.label.values, ct[0]), "XGBoost": metrics(te.label.values, ct[1]),
         "RiskScore": {**metrics(te.label.values, risk_te / 100, policy["thresholds"]["medium"] / 100), "val_pr_auc": val_ap},
         "threshold_sensitivity": sens,
         "data": {"rows": len(df), "train": len(tr), "val": len(va), "test": len(te), "fraud_rate": float(df.label.mean()), "seed": seed,
                  "source": "synthetic (Faker) - replace with real dataset when supplied"}}
    version = f"v{int(time.time())}"
    out = artifact_dir / "models" / version
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(iso, out / "iforest.joblib")
    clf.save_model(out / "xgb.json")
    (out / "meta.json").write_text(json.dumps({"version": version, "feature_names": FEATURE_NAMES, "anomaly_norm": norm, "metrics": m,
                                               "weights": weights, "created_at": time.time()}, indent=1))
    (artifact_dir / "current.json").write_text(json.dumps({"version": version}))
    if not quiet:
        for k in ("IsolationForest", "XGBoost", "RiskScore"):
            print(k, {x: round(m[k][x], 3) for x in ("precision", "recall", "f1", "roc_auc", "pr_auc")}, m[k]["confusion_matrix"])
        print("weights", weights, "| fraud rate", round(m["data"]["fraud_rate"], 3), "| version", version)
    return version, m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    train(**vars(ap.parse_args()))
