import pytest
from app.common.validation import ValidationError, Validator
from app.config import settings
from app.config.settings import load_policy
from app.rules.rule_engine import RuleEngine
from tests.conftest import sample_txn

P = load_policy()
V = lambda: Validator(P, settings.PSEUDONYM_KEY)


def test_valid_event_is_pseudonymised():
    t = sample_txn(ip_address="49.1.2.3")
    ev = V().validate(t)
    assert ev["user_id"] != t["user_id"] and len(ev["user_id"]) == 16
    assert "ip_address" not in ev and ev["ip_hash"] and ev["status"] == "VALIDATED"


@pytest.mark.parametrize("patch", [{"amount": -5}, {"amount": "12"}, {"amount": float("inf")}, {"currency": "rupees"},
                                   {"event_time": "yesterday"}, {"event_time": "2099-01-01T00:00:00+00:00"}, {"user_id": ""}, {"metadata": "x"}])
def test_rejects_bad_input(patch):
    with pytest.raises(ValidationError):
        V().validate(sample_txn(**patch))


def test_missing_required_and_non_object_and_duplicate():
    t = sample_txn(); t.pop("merchant_id")
    with pytest.raises(ValidationError):
        V().validate(t)
    with pytest.raises(ValidationError):
        V().validate([1, 2])
    v, t2 = V(), sample_txn()
    v.validate(t2)
    with pytest.raises(ValidationError, match="duplicate"):
        v.validate(dict(t2))


def feats(**kw):
    return {"txn_count_5m": 1, "location_deviation": 0.0, "secs_since_last": 1e9, **kw}


def test_rules_are_config_driven():
    re_ = RuleEngine(P, settings.PSEUDONYM_KEY)
    base = {"merchant_id": "M1", "country": "IN", "amount": 100, "user_id": "u", "ip_suspicious": 0}
    assert re_.evaluate(base, feats()).hits == []
    assert re_.evaluate({**base, "merchant_id": "M-BLACKLISTED-1"}, feats()).hard["action"] == "BLOCK"
    assert re_.evaluate({**base, "country": "KP"}, feats()).hard["action"] == "REVIEW"
    r = re_.evaluate(base, feats(txn_count_5m=9))
    assert [h["id"] for h in r.hits] == ["EXCESS_VELOCITY"] and r.hard is None and r.score == .5
    assert any(h["id"] == "IMPOSSIBLE_TRAVEL" for h in re_.evaluate(base, feats(location_deviation=1.0, secs_since_last=60)).hits)
