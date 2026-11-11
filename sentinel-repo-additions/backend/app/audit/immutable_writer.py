"""Append-only, hash-chained, HMAC-signed audit trail.
event_hash = SHA256(canonical record incl. prev_hash). Editing any past row breaks every later link.
DB triggers additionally reject UPDATE/DELETE. Corrections are written as new records."""
import hmac
import json
import uuid
from hashlib import sha256 as _sha

from app.common.util import canonical, sha256, utcnow_iso

GENESIS = "GENESIS"
CHAIN_FIELDS = ("audit_id", "record_type", "event_id", "transaction_id", "created_at", "model_versions", "policy_version",
                "risk_score", "risk_category", "decision", "risk_drivers", "payload_hash", "prev_hash", "actor")


class AuditWriter:
    def __init__(self, db, signing_key: bytes):
        self.db, self.key = db, signing_key

    def _sign(self, h):
        return hmac.new(self.key, h.encode(), _sha).hexdigest() if self.key else None

    def append_in_tx(self, cur, record_type, event_id, transaction_id=None, payload=None, model_versions=None,
                     policy_version=None, risk_score=None, risk_category=None, decision=None, risk_drivers=None,
                     actor="system", metadata=None):
        row = cur.execute("SELECT event_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        rec = {"audit_id": str(uuid.uuid4()), "record_type": record_type, "event_id": event_id, "transaction_id": transaction_id,
               "created_at": utcnow_iso(), "model_versions": canonical(model_versions) if model_versions else None,
               "policy_version": policy_version, "risk_score": risk_score, "risk_category": risk_category, "decision": decision,
               "risk_drivers": canonical(risk_drivers) if risk_drivers is not None else None,
               "payload_hash": sha256(canonical(payload or {})), "prev_hash": row[0] if row else GENESIS, "actor": actor}
        rec["event_hash"] = sha256(canonical({k: rec[k] for k in CHAIN_FIELDS}))
        rec["signature"] = self._sign(rec["event_hash"])
        cur.execute("""INSERT INTO audit_log (audit_id,record_type,event_id,transaction_id,created_at,model_versions,policy_version,
            risk_score,risk_category,decision,risk_drivers,payload_hash,prev_hash,event_hash,signature,actor,metadata)
            VALUES (:audit_id,:record_type,:event_id,:transaction_id,:created_at,:model_versions,:policy_version,:risk_score,
            :risk_category,:decision,:risk_drivers,:payload_hash,:prev_hash,:event_hash,:signature,:actor,:metadata)""",
                    {**rec, "metadata": canonical(metadata) if metadata else None})
        return rec

    def append(self, *a, **kw):
        with self.db.tx() as cur:
            return self.append_in_tx(cur, *a, **kw)

    def verify_chain(self):
        """Recompute every hash/signature. Returns (ok, records_checked, first_bad_seq)."""
        prev, n = GENESIS, 0
        for r in self.db.query("SELECT * FROM audit_log ORDER BY seq"):
            ok = r["prev_hash"] == prev and r["event_hash"] == sha256(canonical({k: r[k] for k in CHAIN_FIELDS}))
            if ok and r["signature"] is not None:
                ok = hmac.compare_digest(r["signature"], self._sign(r["event_hash"]) or "")
            if not ok:
                return False, n, r["seq"]
            prev, n = r["event_hash"], n + 1
        return True, n, None

    def recent(self, limit=50, event_id=None):
        sql = "SELECT * FROM audit_log " + ("WHERE event_id=? " if event_id else "") + "ORDER BY seq DESC LIMIT ?"
        return self.db.query(sql, ((event_id, limit) if event_id else (limit,)))

    def record_feedback(self, event_id, ground_truth, analyst_action, reason, source="analyst", analyst="analyst"):
        if ground_truth not in ("FRAUD", "LEGITIMATE", "UNKNOWN"):
            raise ValueError("ground_truth must be FRAUD, LEGITIMATE or UNKNOWN")
        if analyst_action not in ("ALLOW", "BLOCK", "CHALLENGE", "ESCALATE"):
            raise ValueError("analyst_action must be ALLOW, BLOCK, CHALLENGE or ESCALATE")
        if not reason or not reason.strip():
            raise ValueError("reason is required")
        with self.db.tx() as cur:
            d = cur.execute("SELECT decision,risk_score,risk_category,policy_version FROM risk_decisions WHERE event_id=?", (event_id,)).fetchone()
            if not d:
                raise LookupError("unknown event_id")
            cur.execute("INSERT INTO feedback_labels (event_id,ground_truth,analyst_action,feedback_reason,label_source,analyst,label_time) VALUES (?,?,?,?,?,?,?)",
                        (event_id, ground_truth, analyst_action, reason, source, analyst, utcnow_iso()))
            return self.append_in_tx(cur, "OVERRIDE", event_id, payload={"ground_truth": ground_truth, "reason": reason},
                                     policy_version=d["policy_version"], risk_score=d["risk_score"], risk_category=d["risk_category"],
                                     decision=analyst_action, actor=analyst,
                                     metadata={"original_decision": d["decision"], "source": source})
