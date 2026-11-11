"""Central configuration. Environment variables override defaults; policy lives in policy.json (versioned)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = Path(os.getenv("POLICY_PATH", ROOT / "app/config/policy.json"))
ARTIFACT_DIR = Path(os.getenv("ARTIFACT_DIR", ROOT / "artifacts"))
DB_PATH = os.getenv("DB_PATH", str(ROOT / "data/risk.db"))

BUS_BACKEND = os.getenv("BUS_BACKEND", "memory")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
REDIS_URL = os.getenv("REDIS_URL", "")
PSEUDONYM_KEY = os.getenv("PSEUDONYM_KEY", "dev-only-pseudonym-key").encode()
AUDIT_SIGNING_KEY = os.getenv("AUDIT_SIGNING_KEY", "dev-only-audit-key").encode()
TCP_HOST, TCP_PORT = os.getenv("TCP_HOST", "127.0.0.1"), int(os.getenv("TCP_PORT", "9009"))
TCP_TOKEN = os.getenv("TCP_TOKEN", "")
API_HOST, API_PORT = os.getenv("API_HOST", "127.0.0.1"), int(os.getenv("API_PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")
WORKERS = int(os.getenv("WORKERS", "2"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
PARALLEL_ML = os.getenv("PARALLEL_ML", "0") == "1"
MAX_MESSAGE_BYTES = 64 * 1024

TOPICS = {k: f"transactions.{v}" for k, v in {
    "raw": "raw", "validated": "validated", "scored": "risk-scored", "high": "high-risk",
    "audit": "audit", "feedback": "feedback", "dlq": "dlq"}.items()}


def load_policy(path=None) -> dict:
    return json.loads(Path(path or POLICY_PATH).read_text())
