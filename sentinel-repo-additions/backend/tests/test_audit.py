import sqlite3
import pytest
from tests.conftest import drain, sample_txn


def scored(ctx, n=3):
    for i in range(n):
        ctx.ingest.handle_dict(sample_txn(transaction_id=f"T{i}"))
    return drain(ctx)


def test_chain_verifies(ctx):
    scored(ctx)
    ok, n, bad = ctx.audit.verify_chain()
    assert ok and n == 3 and bad is None


def test_update_and_delete_are_blocked(ctx):
    scored(ctx, 1)
    for sql in ("UPDATE audit_log SET decision='ALLOW'", "DELETE FROM audit_log", "UPDATE risk_decisions SET risk_score=0", "DELETE FROM risk_decisions"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            with ctx.db.tx() as c:
                c.execute(sql)


def test_tampering_by_privileged_actor_is_detected(ctx):
    scored(ctx, 4)
    with ctx.db.tx() as c:                                           # attacker with DDL rights drops the trigger...
        c.execute("DROP TRIGGER audit_no_update")
        c.execute("UPDATE audit_log SET risk_score=1 WHERE seq=2")    # ...and edits history
    ok, _, bad = ctx.audit.verify_chain()
    assert not ok and bad == 2


def test_feedback_appends_new_record_not_edit(ctx):
    res = scored(ctx, 1)[0]
    before = ctx.db.query("SELECT COUNT(*) c FROM audit_log")[0]["c"]
    ctx.audit.record_feedback(res["event_id"], "LEGITIMATE", "ALLOW", "customer confirmed by phone")
    assert ctx.db.query("SELECT COUNT(*) c FROM audit_log")[0]["c"] == before + 1
    assert ctx.audit.verify_chain()[0]
    last = ctx.audit.recent(1)[0]
    assert last["record_type"] == "OVERRIDE" and last["actor"] == "analyst"
    with pytest.raises(ValueError):
        ctx.audit.record_feedback(res["event_id"], "MAYBE", "ALLOW", "x")
    with pytest.raises(ValueError):
        ctx.audit.record_feedback(res["event_id"], "FRAUD", "BLOCK", "  ")
    with pytest.raises(LookupError):
        ctx.audit.record_feedback("nope", "FRAUD", "BLOCK", "x")
