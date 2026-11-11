"""Boundary validation + PII minimisation. Required fields are config-driven (policy.json), not hard-coded."""
import math
import re
import time
import uuid
from collections import OrderedDict
from threading import Lock

from app.common.util import canonical, parse_time, pseudonymize, utcnow_iso

KNOWN = {"transaction_id", "user_id", "amount", "currency", "merchant_id", "merchant_category", "device_id",
         "ip_address", "country", "city", "channel", "event_time", "metadata"}
MAX_STR, MAX_META = 128, 4096


class ValidationError(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


class Validator:
    def __init__(self, policy, pseudonym_key: bytes, dedup_size=50_000):
        self.required = policy["required_fields"]
        self.key = pseudonym_key
        self.suspicious_prefixes = tuple(policy["lists"].get("suspicious_ip_prefixes", []))
        self._seen, self._lock, self._cap = OrderedDict(), Lock(), dedup_size

    def validate(self, raw) -> dict:
        errs = []
        if not isinstance(raw, dict):
            raise ValidationError(["payload must be a JSON object"])
        for f in self.required:
            if raw.get(f) in (None, ""):
                errs.append(f"missing required field: {f}")
        for k in ("transaction_id", "user_id", "merchant_id", "device_id", "merchant_category", "country", "city", "channel", "ip_address"):
            v = raw.get(k)
            if v is not None and (not isinstance(v, str) or len(v) > MAX_STR):
                errs.append(f"{k} must be a string up to {MAX_STR} chars")
        amt = raw.get("amount")
        if "amount" in raw and (isinstance(amt, bool) or not isinstance(amt, (int, float)) or not math.isfinite(amt) or not 0 < amt <= 1e9):
            errs.append("amount must be a finite number in (0, 1e9]")
        cur = raw.get("currency")
        if cur is not None and not (isinstance(cur, str) and re.fullmatch(r"[A-Z]{3}", cur)):
            errs.append("currency must be a 3-letter ISO code")
        ts = None
        if raw.get("event_time"):
            try:
                ts = parse_time(str(raw["event_time"])).timestamp()
                if ts > time.time() + 300:
                    errs.append("event_time is in the future")
            except ValueError:
                errs.append("event_time must be ISO-8601")
        if raw.get("metadata") is not None and not isinstance(raw["metadata"], dict):
            errs.append("metadata must be an object")
        if errs:
            raise ValidationError(errs)

        tid = raw["transaction_id"]
        with self._lock:                                   # replay / duplicate protection
            if tid in self._seen:
                raise ValidationError([f"duplicate transaction_id: {tid}"])
            self._seen[tid] = 1
            if len(self._seen) > self._cap:
                self._seen.popitem(last=False)

        meta = dict(raw.get("metadata") or {})
        meta.update({k: v for k, v in raw.items() if k not in KNOWN})
        if len(canonical(meta)) > MAX_META:
            raise ValidationError(["metadata too large"])
        ip = raw.get("ip_address") or ""
        p = lambda v: pseudonymize(self.key, v)
        return {
            "event_id": str(uuid.uuid4()), "transaction_id": tid, "received_at": utcnow_iso(), "status": "VALIDATED",
            "user_id": p(raw["user_id"]), "device_id": p(raw["device_id"]), "ip_hash": p(ip) if ip else "",
            "ip_suspicious": int(bool(ip) and ip.startswith(self.suspicious_prefixes)) if self.suspicious_prefixes else 0,
            "amount": float(amt), "currency": cur, "merchant_id": raw["merchant_id"],
            "merchant_category": raw.get("merchant_category", ""), "country": raw.get("country", ""),
            "city": raw.get("city", ""), "channel": raw.get("channel", ""),
            "event_time": raw["event_time"], "ts": ts, "metadata": meta,
        }
