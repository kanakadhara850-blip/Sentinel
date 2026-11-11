"""Loads versioned model artifacts ONCE; thread-safe read-only inference."""
import json
import time
from pathlib import Path

import joblib
import numpy as np
import xgboost as xgb

from app.features.feature_store import FEATURE_NAMES

FEATURE_LABELS = {"txn_count_5m": "High transaction velocity", "txn_count_15m": "High transaction velocity",
                  "amount_sum_15m": "High spend in 15 minutes", "amount": "Unusual transaction amount",
                  "amount_ratio": "Abnormal amount vs customer history", "device_change_flag": "New device",
                  "new_merchant_flag": "New merchant relationship", "location_deviation": "Unusual geographic behaviour",
                  "is_new_user": "New customer profile", "hour": "Unusual time of day"}


class ModelBundle:
    def __init__(self, path: Path):
        meta = json.loads((path / "meta.json").read_text())
        self.version, self.feature_names = meta["version"], meta["feature_names"]
        self.norm, self.metrics, self.weights, self.path = meta["anomaly_norm"], meta["metrics"], meta.get("weights"), path
        self.iforest = joblib.load(path / "iforest.joblib")
        self.xgb = xgb.XGBClassifier()
        self.xgb.load_model(path / "xgb.json")
        self._booster = self.xgb.get_booster()
        self.predict(np.zeros(len(self.feature_names)))          # warm-up so the first live request is not slow

    @classmethod
    def load(cls, artifact_dir, version=None):
        d = Path(artifact_dir)
        version = version or json.loads((d / "current.json").read_text())["version"]
        return cls(d / "models" / version)

    def vector(self, feats: dict):
        return np.array([float(feats[n]) for n in self.feature_names])

    def predict_iforest(self, x):
        t = time.perf_counter()
        raw = float(-self.iforest.score_samples(x.reshape(1, -1))[0])
        lo, hi = self.norm["lo"], self.norm["hi"]
        return {"raw": raw, "score": float(min(1.0, max(0.0, (raw - lo) / (hi - lo)))), "ms": (time.perf_counter() - t) * 1e3}

    def predict_xgb(self, x):
        t = time.perf_counter()
        p = float(self.xgb.predict_proba(x.reshape(1, -1))[0, 1])
        return {"raw": p, "score": p, "ms": (time.perf_counter() - t) * 1e3}

    def predict(self, x):
        return self.predict_iforest(x), self.predict_xgb(x)

    def contributions(self, x):
        """Exact TreeSHAP values from XGBoost (pred_contribs). Computed only for MEDIUM/HIGH transactions."""
        c = self._booster.predict(xgb.DMatrix(x.reshape(1, -1)), pred_contribs=True)[0][:-1]
        merged = {}
        for n, v in zip(self.feature_names, c):
            merged[FEATURE_LABELS.get(n, n)] = merged.get(FEATURE_LABELS.get(n, n), 0.0) + float(v)
        return merged
