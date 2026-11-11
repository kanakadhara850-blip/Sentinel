"""Config-driven rule engine. Rules live in policy.json; no business rule is embedded in code."""
from app.common.util import pseudonymize

OPS = {"gt": lambda a, b: a > b, "gte": lambda a, b: a >= b, "lt": lambda a, b: a < b,
       "lte": lambda a, b: a <= b, "eq": lambda a, b: a == b, "in_list": lambda a, b: a in b}


class RuleResult:
    def __init__(self, hits):
        self.hits = hits                                       # [{id,label,points,hard,action}]
        self.hard = next((h for h in hits if h["hard"]), None)
        self.score = min(1.0, sum(h["points"] for h in hits) / 100.0)   # normalised 0-1


class RuleEngine:
    def __init__(self, policy, pseudonym_key: bytes):
        self.rules = policy["rules"]
        # customer blacklists hold raw ids in config; compare against pseudonymised ids
        self.lists = {k: set(pseudonymize(pseudonym_key, v) for v in vs) if k.endswith("_users") else set(vs)
                      for k, vs in policy["lists"].items()}

    def evaluate(self, ev, feats) -> RuleResult:
        ctx = {**ev, **feats}
        hits = []
        for r in self.rules:
            ok = True
            for c in r["all"]:
                val = ctx.get(c["field"])
                ref = self.lists.get(c["value"], set()) if c["op"] == "in_list" else c["value"]
                if val is None or not OPS[c["op"]](val, ref):
                    ok = False
                    break
            if ok:
                hits.append({k: r.get(k) for k in ("id", "label", "points", "hard", "action")})
        return RuleResult(hits)
