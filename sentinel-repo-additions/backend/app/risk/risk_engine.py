"""SymPy risk formula, built and lambdified ONCE at start-up (never per transaction).
All components are normalised to 0-1; the weighted sum is divided by the weight total so the score is 0-100.
Weights are symbols, so calibrated weights can be swapped without recompiling and arrays can be scored in bulk."""
import math

import sympy as sp


class RiskEngine:
    def __init__(self, policy, weights=None):
        anomaly, scam, amount_n, vel_n, rule_n = sp.symbols("anomaly scam amount_n vel_n rule_n")
        w_ml, w_amt, w_vel, w_rule, share = sp.symbols("w_ml w_amount w_velocity w_rule anomaly_share")
        ml = share * anomaly + (1 - share) * scam
        self.expr = 100 * (w_ml * ml + w_amt * amount_n + w_vel * vel_n + w_rule * rule_n) / (w_ml + w_amt + w_vel + w_rule)
        self._args = (anomaly, scam, amount_n, vel_n, rule_n, w_ml, w_amt, w_vel, w_rule, share)
        self._fn = sp.lambdify(self._args, self.expr, "numpy")          # compiled once
        self.set_weights(weights or policy["default_weights"])
        self.t_medium, self.t_high = policy["thresholds"]["medium"], policy["thresholds"]["high"]
        self.actions = policy["actions"]

    def set_weights(self, w):
        self.w = tuple(float(w[k]) for k in ("w_ml", "w_amount", "w_velocity", "w_rule", "anomaly_share"))

    @staticmethod
    def amount_norm(amount_ratio):
        """Spend relative to the customer's own history, squashed to 0-1."""
        return min(1.0, math.log1p(max(amount_ratio, 0.0)) / math.log1p(20))

    def score(self, anomaly, scam, amount_n, vel_n, rule_n):
        s = self._fn(anomaly, scam, amount_n, vel_n, rule_n, *self.w)
        return min(100.0, max(0.0, float(s))) if not hasattr(s, "shape") or s.shape == () else s.clip(0, 100)

    def classify(self, score):
        """LOW 0-29.99 | MEDIUM 30-75 | HIGH >75 (thresholds come from the versioned policy)."""
        cat = "HIGH" if score > self.t_high else "MEDIUM" if score >= self.t_medium else "LOW"
        return cat, self.actions[cat]
