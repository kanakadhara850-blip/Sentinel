"""Create a demo database by pushing simulated traffic through the REAL pipeline, plus analyst feedback.
  python scripts/seed_demo_db.py --n 600 --out data/risk.db"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.context import build_context  # noqa: E402
from app.simulation.generator import TxnGenerator  # noqa: E402


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=600); ap.add_argument("--out", default="data/risk.db")
    a = ap.parse_args()
    Path(a.out).unlink(missing_ok=True)
    ctx = build_context(db_path=a.out, workers=1)
    truth = {}
    g = TxnGenerator(seed=2026)
    for ev, y in g.stream(a.n, 0.10):
        r = ctx.ingest.handle_dict(ev); truth[r["event_id"]] = y
    ctx.ingest.handle_dict({"transaction_id": "BAD-1", "amount": -10})                      # one malformed example -> DLQ + audit
    ctx.ingest.handle_dict({**g.scenario("normal")[0][0], "merchant_id": "M-BLACKLISTED-1"})  # hard rule example
    c = ctx.workers.consumers[0]
    while (m := c.poll(0.05)) is not None:
        ctx.workers.handle(m); c.commit()
    # analyst reviews the high-risk queue: labels come from the simulator's ground truth
    hi = ctx.db.query("SELECT event_id, decision FROM risk_decisions WHERE risk_category='HIGH' LIMIT 40")
    for r in hi:
        fraud = truth.get(r["event_id"], 1)
        ctx.audit.record_feedback(r["event_id"], "FRAUD" if fraud else "LEGITIMATE", "BLOCK" if fraud else "ALLOW",
                                  "confirmed by analyst review" if fraud else "false positive: customer verified", "analyst", "analyst.demo")
    print(ctx.db.query("SELECT risk_category, COUNT(*) n FROM risk_decisions GROUP BY 1"), "| chain:", ctx.audit.verify_chain())


if __name__ == "__main__":
    main()
