"""Composition root: builds every component once (models + SymPy expression are loaded here, never per request)."""
from dataclasses import dataclass

from app.audit.immutable_writer import AuditWriter
from app.common.validation import Validator
from app.config import settings
from app.db.database import Database
from app.features.feature_store import make_feature_store
from app.models.inference import ModelBundle
from app.pipeline.processor import Processor
from app.pipeline.worker import WorkerPool
from app.risk.risk_engine import RiskEngine
from app.rules.rule_engine import RuleEngine
from app.streaming.bus import make_bus
from app.transport.tcp_server import IngestService


@dataclass
class Context:
    policy: dict; db: Database; audit: AuditWriter; bus: object; fs: object; bundle: ModelBundle
    processor: Processor; ingest: IngestService; workers: WorkerPool


def build_context(db_path=None, artifact_dir=None, bus_backend=None, workers=None, policy=None) -> Context:
    policy = policy or settings.load_policy()
    db = Database(db_path or settings.DB_PATH)
    audit = AuditWriter(db, settings.AUDIT_SIGNING_KEY)
    bus = make_bus(bus_backend or settings.BUS_BACKEND, settings.KAFKA_BOOTSTRAP, settings.TOPICS)
    fs = make_feature_store(settings.REDIS_URL, policy["velocity"])
    bundle = ModelBundle.load(artifact_dir or settings.ARTIFACT_DIR)
    proc = Processor(policy, bundle, fs, RuleEngine(policy, settings.PSEUDONYM_KEY), RiskEngine(policy), db, audit, settings.PARALLEL_ML)
    ingest = IngestService(Validator(policy, settings.PSEUDONYM_KEY), bus, db, audit, settings.TOPICS, settings.TCP_TOKEN)
    pool = WorkerPool(bus, proc, db, audit, settings.TOPICS, workers or settings.WORKERS, settings.MAX_RETRIES)
    return Context(policy, db, audit, bus, fs, bundle, proc, ingest, pool)
