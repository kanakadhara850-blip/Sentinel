import json
from app.simulation.generator import TxnGenerator
from tests.conftest import drain, sample_txn


def test_end_to_end_normal_and_malformed(ctx):
    ok = ctx.ingest.handle_dict(sample_txn())
    bad = ctx.ingest.handle_dict({"amount": -1})
    assert ok["status"] == "ACCEPTED" and bad["status"] == "REJECTED"
    res = drain(ctx)[0]
    assert 0 <= res["risk_score"] <= 100 and res["risk_category"] in ("LOW", "MEDIUM", "HIGH")
    assert res["model_version"] == ctx.bundle.version and res["policy_version"] == ctx.policy["policy_version"]
    row = ctx.db.query("SELECT * FROM risk_decisions WHERE event_id=?", (ok["event_id"],))[0]
    assert row["decision"] == res["decision"]
    assert ctx.db.query("SELECT COUNT(*) c FROM dlq_events")[0]["c"] == 1
    assert {r["record_type"] for r in ctx.audit.recent(10)} == {"DECISION", "REJECTED"}
    assert len(ctx.db.query("SELECT * FROM model_results WHERE event_id=?", (ok["event_id"],))) == 2
    assert ctx.audit.verify_chain()[0]


def test_hard_rule_short_circuits_ml(ctx):
    r = ctx.ingest.handle_dict(sample_txn(merchant_id="M-BLACKLISTED-1"))
    res = drain(ctx)[0]
    assert res["decision"] == "BLOCK" and res["risk_category"] == "HIGH" and res["rules_triggered"] == ["BLACKLIST_MERCHANT"]
    assert res["risk_score"] > ctx.risk_t if hasattr(ctx, "risk_t") else res["risk_score"] > 75


def test_scam_scores_higher_than_normal(ctx):
    g = TxnGenerator(seed=99)
    normal = []
    for i in range(20):
        ctx.ingest.handle_dict(g.scenario("normal")[0][0])
    normal = [r["risk_score"] for r in drain(ctx)]
    ctx.ingest.handle_dict(g.scenario("scam")[0][0])
    scam = drain(ctx)[0]
    assert scam["risk_score"] > max(sorted(normal)[len(normal) // 2], 30)
    assert scam["risk_drivers"] and scam["decision"] in ("CHALLENGE", "BLOCK")


def test_velocity_burst_raises_risk(ctx):
    g = TxnGenerator(seed=5)
    for ev, _ in g.scenario("high_frequency"):
        ctx.ingest.handle_dict(ev)
    scores = [r["risk_score"] for r in drain(ctx)]
    assert scores[-1] > scores[0]


def test_worker_failure_goes_to_dlq_after_retries(ctx, monkeypatch):
    ctx.workers.max_retries = 2
    monkeypatch.setattr(ctx.processor, "process", lambda ev: (_ for _ in ()).throw(RuntimeError("boom")))
    ctx.ingest.handle_dict(sample_txn())
    drain(ctx)
    d = ctx.db.query("SELECT * FROM dlq_events")
    assert len(d) == 1 and d[0]["stage"] == "PROCESSING" and "boom" in d[0]["error"]


def test_redelivery_is_idempotent(ctx):
    ctx.ingest.handle_dict(sample_txn())
    c = ctx.workers.consumers[0]
    msg = c.poll(0.1)
    ctx.workers.handle(msg); ctx.workers.handle(msg)               # at-least-once redelivery
    assert ctx.db.query("SELECT COUNT(*) c FROM risk_decisions")[0]["c"] == 1
    assert ctx.db.query("SELECT COUNT(*) c FROM audit_log")[0]["c"] == 1
