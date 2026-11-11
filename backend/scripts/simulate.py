"""Transaction simulator. Sends over the real TCP socket.
  python scripts/simulate.py live --rate 5 --fraud-rate 0.1       # Faker live stream
  python scripts/simulate.py scenario scam                         # one named scenario
  python scripts/simulate.py gen-csv --n 5000 --out data/simulated/transactions.csv
  python scripts/simulate.py replay --csv data/simulated/transactions.csv --rate 20"""
import argparse
import csv
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.simulation.generator import SCENARIOS, TxnGenerator  # noqa: E402
from app.transport.tcp_client import TCPClient  # noqa: E402

COLS = ["transaction_id", "user_id", "amount", "currency", "merchant_id", "merchant_category", "device_id", "ip_address", "country", "city", "channel", "event_time"]


def now(ev):
    return {**ev, "event_time": datetime.now(timezone.utc).isoformat()}      # live mode stamps current time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["live", "scenario", "gen-csv", "replay"])
    ap.add_argument("name", nargs="?", default="scam", choices=SCENARIOS)
    ap.add_argument("--rate", type=float, default=5)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--fraud-rate", type=float, default=0.08)
    ap.add_argument("--out", default="data/simulated/transactions.csv")
    ap.add_argument("--csv")
    a = ap.parse_args()
    g = TxnGenerator(seed=random.randrange(1 << 30))
    if a.mode == "gen-csv":
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "w", newline="") as f:
            w = csv.DictWriter(f, COLS + ["is_fraud"]); w.writeheader()
            for ev, y in g.stream(a.n or 5000, a.fraud_rate): w.writerow({**ev, "is_fraud": y})
        return print("wrote", a.out)
    c = TCPClient()
    if a.mode == "scenario":
        for ev, _ in g.scenario(a.name): print(a.name, c.send(now(ev)))
    elif a.mode == "replay":
        with open(a.csv) as f:
            for i, row in enumerate(csv.DictReader(f)):
                row.pop("is_fraud", None); row["amount"] = float(row["amount"])
                r = c.send(now(row)); i % 50 == 0 and print(i, r["status"]); time.sleep(1 / a.rate)
    else:
        i = 0
        while a.n == 0 or i < a.n:
            for ev, _ in g.stream(1, a.fraud_rate):
                print(c.send(now(ev))["status"], end=" ", flush=True); i += 1; time.sleep(1 / a.rate)


if __name__ == "__main__":
    main()
