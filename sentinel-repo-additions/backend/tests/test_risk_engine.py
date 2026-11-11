import numpy as np
from app.config.settings import load_policy
from app.risk.risk_engine import RiskEngine


def test_score_bounds_and_monotonic():
    r = RiskEngine(load_policy())
    assert r.score(0, 0, 0, 0, 0) == 0.0
    assert abs(r.score(1, 1, 1, 1, 1) - 100.0) < 1e-9
    assert r.score(.9, .9, .5, .5, 0) > r.score(.1, .1, .5, .5, 0)


def test_threshold_boundaries():
    r = RiskEngine(load_policy())
    assert r.classify(29.99) == ("LOW", "ALLOW")
    assert r.classify(30.0) == ("MEDIUM", "CHALLENGE")
    assert r.classify(75.0) == ("MEDIUM", "CHALLENGE")
    assert r.classify(75.01) == ("HIGH", "BLOCK")


def test_lambdified_once_and_vectorised():
    r = RiskEngine(load_policy())
    fn = r._fn
    r.score(.5, .5, .5, .5, .5); r.score(.1, .2, .3, .4, .5)
    assert r._fn is fn                                           # never rebuilt per transaction
    out = r.score(np.array([0, 1.0]), np.array([0, 1.0]), np.array([0, 1.0]), np.array([0, 1.0]), np.array([0, 1.0]))
    assert out.shape == (2,) and out[0] == 0 and abs(out[1] - 100) < 1e-9


def test_weights_swap_without_recompile():
    r = RiskEngine(load_policy())
    r.set_weights({"w_ml": 1, "w_amount": 0, "w_velocity": 0, "w_rule": 0, "anomaly_share": 0})
    assert abs(r.score(0, .8, 1, 1, 1) - 80) < 1e-9
