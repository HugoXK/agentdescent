"""#950: a promotion decision must see what reviewing the diff costs.

A +0.02 diff over 40 files is not the same product decision as a +0.02 diff over
one file: the first spends the team's attention. These tests pin the review-cost
estimate, the two opt-in limits, and that leaving both at their defaults changes
nothing at all.

Written against ``agentdescent.promotion`` as a module so that this file still
collects on a tree without the new names: the red is the assertion that the
field is missing, not an import error.
"""

import pytest

from agentdescent import promotion
from agentdescent.evalops import EvalResult
from agentdescent.safety_controller import canary


def _eval(*, passed=True, delta=0.02, n=20):
    return EvalResult(
        eval_id="eval", dataset_id="ds", version=1, content_hash="hash",
        n=n, score=0.7, baseline=0.6, delta=delta, ci=(0.005, 0.035),
        passed=passed, cost=0.0, per_task={}, detail="ok")


def _canary():
    incumbent = {f"t{i}": 0.5 for i in range(6)}
    return canary(incumbent, {key: 0.6 for key in incumbent})


def _request(**overrides):
    values = dict(artifact_id="skill-1", eval_result=_eval(), contaminated=False,
                  canary=_canary(), risk=0.2, approved=True)
    values.update(overrides)
    return promotion.PromotionRequest(**values)


def _review_cost_cls():
    cls = getattr(promotion, "ReviewCost", None)
    assert cls is not None, "promotion.ReviewCost is missing (#950)"
    return cls


def _cost(**kwargs):
    return _review_cost_cls().estimate(**kwargs)


def _rules(**kwargs):
    fields = getattr(promotion.PromotionRules, "__dataclass_fields__", {})
    for name in kwargs:
        assert name in fields, f"PromotionRules has no {name} field (#950)"
    return promotion.PromotionRules(**kwargs)


def _wide():
    return _cost(files_changed=40, lines_changed=800, blast_radius=0.4,
                 risk=0.6, evidence_items=4)


def _narrow():
    return _cost(files_changed=1, lines_changed=12, blast_radius=0.1,
                 risk=0.2, evidence_items=2)


def test_the_two_limits_default_to_off():
    rules = promotion.PromotionRules()
    assert getattr(rules, "max_review_minutes", None) == 0.0
    assert getattr(rules, "max_review_cost", None) == 0.0


def test_review_cost_shows_the_inputs_that_produced_the_estimate():
    cost = _wide()
    payload = cost.to_dict()
    for key in ("files_changed", "lines_changed", "blast_radius", "risk",
                "risk_tier", "evidence_items", "review_minutes"):
        assert key in payload, key
    assert payload["files_changed"] == 40
    assert payload["lines_changed"] == 800
    assert payload["evidence_items"] == 4
    assert payload["risk_tier"] == cost.risk_tier
    assert payload["review_minutes"] > 0
    assert payload["review_minutes"] == pytest.approx(cost.review_minutes)


def test_a_wider_diff_costs_more_than_a_narrow_one():
    assert _wide().review_minutes > _narrow().review_minutes
    assert _wide().cost > _narrow().cost


def test_a_forty_file_diff_is_deferred_under_a_review_minute_limit():
    rules = _rules(max_review_minutes=30.0)
    decision = promotion.promote(_request(review_cost=_wide()), rules)
    assert decision.action == promotion.PromotionAction.DEFER
    assert not decision.accepted
    assert "review" in " ".join(decision.reasons).lower()
    assert decision.evidence["review_cost"]["files_changed"] == 40


def test_a_one_file_diff_passes_the_same_limit():
    rules = _rules(max_review_minutes=30.0)
    decision = promotion.promote(_request(review_cost=_narrow()), rules)
    assert decision.action == promotion.PromotionAction.PROMOTE
    assert decision.accepted


def test_the_cost_limit_defers_a_wide_diff_and_passes_a_narrow_one():
    limit = _narrow().cost + (_wide().cost - _narrow().cost) / 2.0
    rules = _rules(max_review_cost=limit)
    assert promotion.promote(_request(review_cost=_wide()), rules).action \
        == promotion.PromotionAction.DEFER
    assert promotion.promote(_request(review_cost=_narrow()), rules).action \
        == promotion.PromotionAction.PROMOTE


def test_the_decision_reports_attention_per_accepted_gain():
    decision = promotion.promote(_request(review_cost=_wide()),
                                 _rules(max_review_minutes=30.0))
    # minutes a reviewer spends per +0.01 of held-out gain
    expected = _wide().review_minutes / (_eval().delta / 0.01)
    assert decision.evidence["attention_per_accepted_gain"] == \
        pytest.approx(expected, rel=1e-6)


def test_defaults_leave_promotion_byte_for_byte_unchanged():
    decision = promotion.promote(_request())
    assert decision.action == promotion.PromotionAction.PROMOTE
    assert decision.accepted
    assert "review_cost" not in decision.evidence
    assert "attention_per_accepted_gain" not in decision.evidence
    # nothing in the default path may move: this hash is the one main produced
    # for the same request at 7b26ddb6, before #950 existed.
    assert decision.decision_hash == (
        "69fe94f3234f922acb971ad38b25cc0b401fbff22351e9a2ec1e060a974c8b48")
    assert decision.evidence_hash == (
        "2642c12d5905b763591d34649ddc69ca14c5e9b5fa29dc98a493d6b289a55601")


def test_review_cost_rejects_impossible_inputs():
    cls = _review_cost_cls()
    with pytest.raises(ValueError):
        cls.estimate(files_changed=-1, lines_changed=0)
    with pytest.raises(ValueError):
        cls.estimate(files_changed=1, lines_changed=0, evidence_items=-2)
