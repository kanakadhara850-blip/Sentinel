"""Faker-based synthetic transaction generator with labelled scenarios.
Labels (is_fraud) are returned separately and are NEVER included in the event sent to the pipeline.
No external dataset was supplied, so the canonical schema (see app/common/validation.py) is defined by this project."""
import random
from datetime import datetime, timedelta, timezone

from faker import Faker

SCENARIOS = ["normal", "high_frequency", "unusual_amount", "new_device", "unusual_location", "suspicious_merchant", "repeated", "scam"]
RISKY_CATEGORIES = ["crypto_exchange", "gift_cards", "wire_transfer", "online_gambling"]
SAFE_CATEGORIES = ["grocery", "fuel", "restaurant", "electronics", "travel", "utilities", "pharmacy"]
COUNTRIES = ["IN", "IN", "IN", "IN", "US", "GB", "SG", "AE"]


class TxnGenerator:
    def __init__(self, n_users=300, seed=7, start=None):
        self.rng = random.Random(seed)
        Faker.seed(seed)
        self.fk = Faker("en_IN")
        self.clock = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.users = [{"id": f"C{self.fk.unique.random_number(digits=7, fix_len=True)}", "city": self.fk.city(), "country": "IN",
                       "devices": [self.fk.uuid4()[:12] for _ in range(self.rng.randint(1, 2))],
                       "merchants": [(f"M{self.rng.randint(100, 400)}", self.rng.choice(SAFE_CATEGORIES)) for _ in range(5)],
                       "avg": self.rng.choice([400, 900, 1800, 3500, 7000]), "ip": f"49.{self.rng.randint(1, 250)}.{self.rng.randint(1, 250)}.{self.rng.randint(1, 250)}"}
                      for _ in range(n_users)]

    def _event(self, u, amount=None, device=None, merchant=None, city=None, country=None, ip=None, dt=0.0):
        self.clock += timedelta(seconds=dt)
        m = merchant or self.rng.choice(u["merchants"])
        amt = amount if amount is not None else max(20.0, self.rng.lognormvariate(0, 0.5) * u["avg"])
        return {"transaction_id": f"T{self.fk.uuid4()[:14]}", "user_id": u["id"], "amount": round(amt, 2), "currency": "INR",
                "merchant_id": m[0], "merchant_category": m[1], "device_id": device or self.rng.choice(u["devices"]),
                "ip_address": ip or u["ip"], "country": country or u["country"], "city": city or u["city"],
                "channel": self.rng.choice(["web", "mobile", "pos"]), "event_time": self.clock.isoformat()}

    def scenario(self, name, u=None):
        """Returns list of (event, is_fraud)."""
        u, r = u or self.rng.choice(self.users), self.rng
        new_dev, new_city = self.fk.uuid4()[:12], self.fk.city()
        risky = (f"M{r.randint(900, 999)}", r.choice(RISKY_CATEGORIES))
        if name == "normal":
            c = r.random()   # a few benign-but-unusual legit events keep the problem realistic
            if c < 0.03:  return [(self._event(u, device=new_dev), 0)]
            if c < 0.05:  return [(self._event(u, city=new_city, country=r.choice(COUNTRIES)), 0)]
            if c < 0.07:  return [(self._event(u, amount=u["avg"] * r.uniform(4, 7)), 0)]
            return [(self._event(u), 0)]
        if name == "high_frequency":
            return [(self._event(u, amount=u["avg"] * r.uniform(.5, 2), dt=r.uniform(3, 25)), 1) for _ in range(r.randint(7, 11))]
        if name == "unusual_amount":
            return [(self._event(u, amount=u["avg"] * r.uniform(12, 40)), 1)]
        if name == "new_device":
            return [(self._event(u, device=new_dev, amount=u["avg"] * r.uniform(2, 6), merchant=risky), 1)]
        if name == "unusual_location":
            return [(self._event(u, city=new_city, country=r.choice(["US", "GB", "AE", "RU"]), amount=u["avg"] * r.uniform(3, 8)), 1)]
        if name == "suspicious_merchant":
            return [(self._event(u, merchant=risky, amount=u["avg"] * r.uniform(5, 15)), 1)]
        if name == "repeated":
            a, m = u["avg"] * r.uniform(2, 4), r.choice(u["merchants"])
            return [(self._event(u, amount=a, merchant=m, dt=r.uniform(10, 40)), 1) for _ in range(r.randint(4, 6))]
        if name == "scam":
            return [(self._event(u, device=new_dev, city=new_city, country=r.choice(["US", "AE", "SG"]), merchant=risky,
                                 amount=u["avg"] * r.uniform(15, 50), ip=f"10.66.{r.randint(1, 250)}.{r.randint(1, 250)}"), 1)]
        raise ValueError(name)

    def stream(self, n, fraud_rate=0.04):
        """Chronological stream of (event, is_fraud); roughly `fraud_rate` of slots are attack scenarios."""
        out = []
        while len(out) < n:
            self.clock += timedelta(seconds=self.rng.expovariate(1 / 2.0))
            name = self.rng.choice(SCENARIOS[1:]) if self.rng.random() < fraud_rate else "normal"
            out.extend(self.scenario(name))
        return out[:n]
