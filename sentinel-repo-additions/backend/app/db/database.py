"""SQLite access layer. One serialized connection (WAL); every pipeline write is a single atomic transaction."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from app.common.util import canonical, utcnow_iso


class Database:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = RLock()
        self.conn.executescript((Path(__file__).parent / "schema_sqlite.sql").read_text())
        self.conn.execute("PRAGMA synchronous=NORMAL")

    @contextmanager
    def tx(self):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                yield cur
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise

    def query(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # ---- registry ----
    def register_versions(self, policy, bundle):
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO policy_versions VALUES (?,?,?)", (policy["policy_version"], canonical(policy), utcnow_iso()))
            for name in ("IsolationForest", "XGBoost"):
                c.execute("INSERT OR IGNORE INTO model_versions VALUES (?,?,?,?,?)",
                          (name, bundle.version, json.dumps(bundle.metrics.get(name, {})), json.dumps(bundle.feature_names), utcnow_iso()))

    # ---- pipeline writes ----
    def save_decision(self, cur, ev, feats, result, model_rows):
        now = utcnow_iso()
        cur.execute("INSERT INTO transaction_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ev["event_id"], ev["transaction_id"], ev["user_id"], ev["device_id"], ev["ip_hash"], ev["amount"], ev["currency"],
                     ev["merchant_id"], ev["merchant_category"], ev["country"], ev["city"], ev["channel"], ev["event_time"],
                     ev["received_at"], canonical(ev["metadata"]), "SCORED"))
        cur.execute("INSERT INTO feature_snapshots VALUES (?,?,?)", (ev["event_id"], canonical(feats), now))
        for m in model_rows:
            cur.execute("INSERT INTO model_results (event_id,model_name,model_version,raw_output,normalized_score,inference_ms,top_features_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (ev["event_id"], m["name"], m["version"], m["raw"], m["score"], m["ms"], canonical(m.get("top")), now))
        cur.execute("INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ev["event_id"], result["anomaly_score"], result["scam_probability"], result["rule_score"], result["velocity_score"],
                     result["risk_score"], result["risk_category"], result["decision"], canonical(result["risk_drivers"]),
                     canonical(result["rules_triggered"]), result["policy_version"], result["latency_ms"], now))

    def save_dlq(self, event_id, stage, error, payload_hash=None):
        with self.tx() as c:
            c.execute("INSERT INTO dlq_events (event_id,stage,error,payload_hash,created_at) VALUES (?,?,?,?,?)",
                      (event_id, stage, error[:500], payload_hash, utcnow_iso()))

    def event_exists(self, event_id):
        return bool(self.query("SELECT 1 FROM risk_decisions WHERE event_id=?", (event_id,)))
