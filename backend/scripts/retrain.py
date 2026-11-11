"""Feedback -> retraining. Joins analyst-confirmed labels (FRAUD/LEGITIMATE) with their stored feature snapshots, retrains, and
promotes the new model only if its test PR-AUC is not worse than the current model's (promotion gate). Old versions are kept.
  python scripts/retrain.py"""
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings  # noqa: E402
from app.db.database import Database  # noqa: E402
from app.models.train import train  # noqa: E402


def main():
    db = Database(settings.DB_PATH)
    rows = db.query("""SELECT f.features_json, l.ground_truth FROM feedback_labels l JOIN feature_snapshots f USING (event_id)
                       WHERE l.ground_truth IN ('FRAUD','LEGITIMATE')""")
    extra = pd.DataFrame([{**json.loads(r["features_json"]), "label": int(r["ground_truth"] == "FRAUD")} for r in rows])
    print(f"{len(extra)} analyst labels available")
    cur_path = settings.ARTIFACT_DIR / "current.json"
    old = json.loads(cur_path.read_text())["version"] if cur_path.exists() else None
    old_ap = json.loads((settings.ARTIFACT_DIR / "models" / old / "meta.json").read_text())["metrics"]["XGBoost"]["pr_auc"] if old else -1
    backup = cur_path.read_text() if old else None
    new, m = train(extra=extra, quiet=True)
    if m["XGBoost"]["pr_auc"] + 1e-9 >= old_ap:
        print(f"PROMOTED {new} (PR-AUC {m['XGBoost']['pr_auc']:.3f} vs {old_ap:.3f}). Restart the backend to load it.")
    else:
        cur_path.write_text(backup)
        print(f"NOT promoted: {new} PR-AUC {m['XGBoost']['pr_auc']:.3f} < {old_ap:.3f}; staying on {old}")


if __name__ == "__main__":
    main()
