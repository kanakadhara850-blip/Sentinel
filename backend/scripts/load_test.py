"""Latency + throughput benchmark of the synchronous decision path (features->rules->ML->risk->decision->audit commit).
  python scripts/load_test.py --n 5000 --workers 4
Reports measured numbers only; compare against the 50 ms target on YOUR hardware."""
import argparse
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.context import build_context  # noqa: E402
from app.simulation.generator import TxnGenerator  # noqa: E402


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=3000); ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    ctx = build_context(db_path=str(Path(tempfile.mkdtemp()) / "bench.db"), workers=a.workers)
    evs = []
    for ev, _ in TxnGenerator(seed=3).stream(a.n, 0.08):
        r = ctx.ingest.handle_dict(ev); evs.append(r)
    msgs = []
    c = ctx.workers.consumers[0]
    while (m := c.poll(0.05)) is not None: msgs.append(m)
    lat, chunks = [], [msgs[i::a.workers] for i in range(a.workers)]
    def run(ch):
        for m in ch:
            t = time.perf_counter(); ctx.processor.process(m); lat.append((time.perf_counter() - t) * 1e3)
    t0 = time.perf_counter()
    ts = [threading.Thread(target=run, args=(ch,)) for ch in chunks]; [t.start() for t in ts]; [t.join() for t in ts]
    wall = time.perf_counter() - t0
    lat.sort(); q = lambda p: lat[min(len(lat) - 1, int(len(lat) * p))]
    print(f"events={len(lat)} workers={a.workers} throughput={len(lat) / wall:.0f}/s  p50={q(.5):.2f}ms p95={q(.95):.2f}ms p99={q(.99):.2f}ms max={lat[-1]:.2f}ms mean={statistics.mean(lat):.2f}ms")
    print("target <50ms p95:", "MET" if q(.95) < 50 else "NOT MET", "(measured on this machine, SQLite + in-memory bus)")
    print("audit chain intact:", ctx.audit.verify_chain())


if __name__ == "__main__":
    main()
