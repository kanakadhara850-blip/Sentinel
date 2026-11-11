import hashlib
import hmac
import json
from datetime import datetime, timezone


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def pseudonymize(key: bytes, value: str) -> str:
    """Keyed hash so raw identifiers are never stored or streamed."""
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:16]


def parse_time(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def to_epoch(s: str) -> float:
    return parse_time(s).timestamp()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
