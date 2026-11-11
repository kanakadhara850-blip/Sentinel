"""Sliding-window behavioural features. Memory backend for dev/tests, Redis backend for deployment.
Features are computed from state BEFORE the current event is added to the profile (no target/self leakage),
then the event is recorded. The same code path is used for training and inference (no train/serve skew)."""
import json
from collections import defaultdict, deque
from threading import Lock

FEATURE_NAMES = ["amount", "amount_ratio", "txn_count_5m", "txn_count_15m", "amount_sum_15m", "device_change_flag",
                 "new_merchant_flag", "location_deviation", "is_new_user", "hour"]


def _derive(ev, hist, n, total, devices, merchants, last_country, last_city, last_ts, vel):
    ts, amt = ev["ts"], ev["amount"]
    c5 = 1 + sum(1 for t, _ in hist if ts - t <= 300)
    c15 = 1 + sum(1 for t, _ in hist if ts - t <= 900)
    s15 = amt + sum(a for t, a in hist if ts - t <= 900)
    avg = total / n if n else amt
    known = n > 0
    loc = 0.0
    if known and last_country and ev["country"] and ev["country"] != last_country:
        loc = 1.0
    elif known and last_city and ev["city"] and ev["city"] != last_city:
        loc = 0.5
    f = {"amount": amt, "avg_amount_hist": avg, "amount_ratio": min(amt / (avg + 1e-9), 50.0), "txn_count_5m": c5,
         "txn_count_15m": c15, "amount_sum_15m": s15, "device_change_flag": int(known and ev["device_id"] not in devices),
         "new_merchant_flag": int(known and ev["merchant_id"] not in merchants), "location_deviation": loc,
         "is_new_user": int(not known), "hour": int((ts % 86400) // 3600), "secs_since_last": (ts - last_ts) if known else 1e9}
    f["velocity_score"] = min(1.0, 0.6 * c5 / vel["limit_5m"] + 0.4 * c15 / vel["limit_15m"])
    return f


class MemoryFeatureStore:
    backend = "memory"

    def __init__(self, velocity):
        self.vel, self.lock = velocity, Lock()
        self.p = defaultdict(lambda: {"n": 0, "total": 0.0, "dev": set(), "mer": set(), "country": "", "city": "", "ts": 0.0, "hist": deque()})

    def update_and_get(self, ev):
        with self.lock:
            p = self.p[ev["user_id"]]
            while p["hist"] and ev["ts"] - p["hist"][0][0] > 900:
                p["hist"].popleft()
            f = _derive(ev, p["hist"], p["n"], p["total"], p["dev"], p["mer"], p["country"], p["city"], p["ts"], self.vel)
            p["hist"].append((ev["ts"], ev["amount"]))
            p["n"] += 1; p["total"] += ev["amount"]; p["dev"].add(ev["device_id"]); p["mer"].add(ev["merchant_id"])
            p["country"], p["city"], p["ts"] = ev["country"] or p["country"], ev["city"] or p["city"], ev["ts"]
            return f

    def ping(self):
        return True


class RedisFeatureStore:
    """Redis layout: z:{u} zset(ts -> 'eventid|amount'), p:{u} hash(n,total,country,city,ts), d:{u}/m:{u} sets. One pipeline round-trip."""
    backend = "redis"

    def __init__(self, url, velocity):
        import redis
        self.r, self.vel = redis.Redis.from_url(url, decode_responses=True), velocity

    def ping(self):
        try:
            return bool(self.r.ping())
        except Exception:
            return False

    def update_and_get(self, ev):
        u, ts = ev["user_id"], ev["ts"]
        pipe = self.r.pipeline()
        pipe.zremrangebyscore(f"z:{u}", 0, ts - 900)
        pipe.zrangebyscore(f"z:{u}", ts - 900, "+inf")
        pipe.hgetall(f"p:{u}"); pipe.smembers(f"d:{u}"); pipe.smembers(f"m:{u}")
        _, rows, prof, devs, mers = pipe.execute()
        hist = [(t, float(m.split("|")[1])) for m, t in ((x, float(self.r.zscore(f"z:{u}", x) or 0)) for x in rows)] if rows else []
        n = int(prof.get("n", 0))
        f = _derive(ev, hist, n, float(prof.get("total", 0)), devs, mers, prof.get("country", ""), prof.get("city", ""),
                    float(prof.get("ts", 0)), self.vel)
        w = self.r.pipeline()
        w.zadd(f"z:{u}", {f"{ev['event_id']}|{ev['amount']}": ts}); w.expire(f"z:{u}", 3600)
        w.hset(f"p:{u}", mapping={"n": n + 1, "total": float(prof.get("total", 0)) + ev["amount"],
                                   "country": ev["country"] or prof.get("country", ""), "city": ev["city"] or prof.get("city", ""), "ts": ts})
        w.sadd(f"d:{u}", ev["device_id"]); w.sadd(f"m:{u}", ev["merchant_id"]); w.execute()
        return f


def make_feature_store(redis_url, velocity):
    if redis_url:
        try:
            s = RedisFeatureStore(redis_url, velocity)
            if s.ping():
                return s
        except Exception:
            pass
    return MemoryFeatureStore(velocity)       # fallback: baseline in-process store
