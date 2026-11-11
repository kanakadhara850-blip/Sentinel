"""Synchronous decision path: features -> rules -> (hard rule short-circuit) -> IsolationForest || XGBoost -> SymPy risk ->
classification -> decision -> atomic persistence (event, features, model results, decision, audit record)."""
import time
from concurrent.futures import ThreadPoolExecutor

from app.common.util import utcnow_iso


class Processor:
    def __init__(self, policy, bundle, feature_store, rules, risk, db, audit, parallel_ml=False):
        self.policy, self.bundle, self.fs, self.rules, self.risk, self.db, self.audit = policy, bundle, feature_store, rules, risk, db, audit
        if bundle.weights:
            risk.set_weights(bundle.weights)                      # use calibrated weights stored with the model version
        self.pool = ThreadPoolExecutor(2) if parallel_ml else None
        db.register_versions(policy, bundle)

    def process(self, ev):
        t0 = time.perf_counter()
        feats = self.fs.update_and_get(ev)
        t_feat = time.perf_counter()
        rr = self.rules.evaluate(ev, feats)
        hard = rr.hard
        anomaly = scam = 0.0
        model_rows, x = [], None
        if not hard:                                              # hard-risk rules skip expensive ML entirely
            x = self.bundle.vector(feats)
            if self.pool:
                fi, fx = self.pool.submit(self.bundle.predict_iforest, x), self.pool.submit(self.bundle.predict_xgb, x)
                iso, xg = fi.result(), fx.result()
            else:
                iso, xg = self.bundle.predict(x)
            anomaly, scam = iso["score"], xg["score"]
            model_rows = [{"name": "IsolationForest", "version": self.bundle.version, **iso},
                          {"name": "XGBoost", "version": self.bundle.version, **xg}]
        t_ml = time.perf_counter()
        score = self.risk.score(anomaly, scam, self.risk.amount_norm(feats["amount_ratio"]), feats["velocity_score"], rr.score)
        category, decision = self.risk.classify(score)
        if hard:                                                   # policy override: hard rules force HIGH + their action
            score, category, decision = max(score, self.risk.t_high + 0.01), "HIGH", hard["action"]
        drivers = self._drivers(x, score, rr, category) if category != "LOW" else []
        latency = (time.perf_counter() - t0) * 1e3
        result = {
            "event_id": ev["event_id"], "transaction_id": ev["transaction_id"], "amount": ev["amount"], "currency": ev["currency"],
            "risk_score": round(float(score), 2), "risk_category": category, "decision": decision,
            "anomaly_score": round(anomaly, 4), "scam_probability": round(scam, 4), "rule_score": round(rr.score, 4),
            "velocity_score": round(feats["velocity_score"], 4), "risk_drivers": drivers, "rules_triggered": [h["id"] for h in rr.hits],
            "model_version": self.bundle.version, "policy_version": self.policy["policy_version"], "latency_ms": round(latency, 2),
            "latency_breakdown_ms": {"features": round((t_feat - t0) * 1e3, 2), "ml": round((t_ml - t_feat) * 1e3, 2)},
            "merchant": ev["merchant_id"], "city": ev["city"], "country": ev["country"], "channel": ev["channel"], "user": ev["user_id"][:8],
            "device": "New device" if feats["device_change_flag"] else "Known device", "timestamp": ev["event_time"], "processed_at": utcnow_iso()}
        with self.db.tx() as cur:                                  # one atomic write; audit is part of the same commit
            self.db.save_decision(cur, ev, feats, result, model_rows if not hard else
                                  [{"name": "IsolationForest", "version": self.bundle.version, "raw": None, "score": None, "ms": 0, "top": "skipped: hard rule"}])
            self.audit.append_in_tx(cur, "DECISION", ev["event_id"], ev["transaction_id"], payload={"features": feats, "rules": result["rules_triggered"]},
                                    model_versions={"IsolationForest": self.bundle.version, "XGBoost": self.bundle.version},
                                    policy_version=result["policy_version"], risk_score=result["risk_score"], risk_category=category,
                                    decision=decision, risk_drivers=drivers, metadata={"latency_ms": result["latency_ms"]})
        return result

    def _drivers(self, x, score, rr, category):
        """Top-3 drivers: exact TreeSHAP from XGBoost (shares of the score) + triggered rules (their weighted points)."""
        out = []
        if x is not None:
            pos = {k: v for k, v in self.bundle.contributions(x).items() if v > 0}
            tot = sum(pos.values()) or 1.0
            out += [{"name": k, "pts": round(score * v / tot, 1), "source": "xgboost_shap"} for k, v in pos.items()]
        wsum = sum(self.risk.w[:4])
        out += [{"name": h["label"], "pts": round(h["points"] * self.risk.w[3] / wsum if not h["hard"] else score, 1), "source": "rule"} for h in rr.hits]
        return sorted(out, key=lambda d: -d["pts"])[:3]
