"""Cost per accepted diff, and the quality-per-cost gate (#945).

The gate decides "is the candidate better on held-out?". It never decides "was
that improvement worth what it cost", so a candidate that adds +0.10 for five
times the tokens can beat one that adds +0.09 for 1.1x. This module is the
second ledger: a per-diff cost block, the derived efficiency, the acceptance
option that refuses a quality gain bought with a cost blow-up, and the report
that states cost per accepted diff and per point of gain.

The one rule every test here enforces: **missing cost is `unknown`, never
zero**. There is no benchmark behind a ports guard, no billing table and no
provider price feed in this slice; a missing number is reported as missing and,
when a caller demands cost, the decision is `defer` -- never a silent pass and
never a rejection dressed as evidence.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentdescent.agents import Usage
from agentdescent.cost import (
    Cost, CostPolicy, CostReport, cost_efficiency, cost_report,
    cost_status,
)
from agentdescent.evalops import EvalResult
from agentdescent.evolvable import Diff, EvidenceCard
from agentdescent.policies import AcceptDecision, MergeContext
from agentdescent.promotion import (
    PromotionAction, PromotionRequest, PromotionRules, promote,
)
from agentdescent.safety_controller import canary


# -- fakes ------------------------------------------------------------------


class _AcceptAll:
    """A stand-in gate, so these tests pin the cost rule, not the Beta gate."""

    def accept(self, ctx: MergeContext) -> AcceptDecision:
        return AcceptDecision(
            True, "committed", "",
            observed_delta=ctx.rate(ctx.cand_counts) - ctx.rate(ctx.base_counts))


class _RejectAll:
    def accept(self, ctx: MergeContext) -> AcceptDecision:
        return AcceptDecision(False, "no-improvement", "gate said no")


def _card(*ops: str, tokens: int = 0, wallclock: float = 0.0) -> EvidenceCard:
    return EvidenceCard(
        diff=Diff(diff_id="d-1", target="skill", ops={op: "x" for op in ops}),
        base_version={"skill": 1}, touched=["skill"],
        cost_tokens=tokens, cost_wallclock=wallclock)


def _ctx(cards=(), *, base=(6.0, 4.0), cand=(8.0, 2.0),
         cost=None) -> MergeContext:
    artifact = SimpleNamespace(id="skill", version=1, state={"rule": "old"})
    candidate = SimpleNamespace(id="skill", version=2, state={"rule": "new"})
    return MergeContext(
        artifact=artifact, candidate=candidate, cards=tuple(cards),
        base_counts=base, cand_counts=cand,
        diff=Diff(diff_id="d-1", target="skill", ops={"rule": "new"}),
        diff_cost=cost)


def _eval(*, passed=True, delta=0.1, n=20) -> EvalResult:
    return EvalResult(
        eval_id="eval", dataset_id="ds", version=1, content_hash="hash",
        n=n, score=0.7, baseline=0.6, delta=delta, ci=(0.02, 0.18),
        passed=passed, cost=0.0, per_task={}, detail="ok")


def _canary():
    incumbent = {f"t{i}": 0.5 for i in range(6)}
    return canary(incumbent, {key: 0.6 for key in incumbent})


def _promotion_request(**overrides) -> PromotionRequest:
    values = dict(
        artifact_id="skill-1", eval_result=_eval(), contaminated=False,
        canary=_canary(), risk=0.2, approved=True)
    values.update(overrides)
    return PromotionRequest(**values)


# -- the per-diff cost block ------------------------------------------------


def test_usage_splits_tokens_and_leaves_unmeasured_usd_unknown():
    cost = Cost.from_usage(Usage(calls=3, prompt_tokens=1_000,
                                 completion_tokens=500, seconds=2.5))
    assert cost.calls == 3
    assert cost.prompt_tokens == 1_000
    assert cost.completion_tokens == 500
    assert cost.tokens == 1_500
    assert cost.wallclock == pytest.approx(2.5)
    assert cost.usd is None          # we never invent a price
    assert cost.known is True
    assert cost_efficiency(0.1, cost) == pytest.approx(0.1 * 1000 / 1_500)


def test_cost_from_cards_is_the_cost_of_the_card_that_justified_the_diff():
    cost = Cost.from_cards([_card("rule", tokens=900, wallclock=1.5),
                            _card("rule", tokens=100, wallclock=0.5)])
    assert cost.tokens == 1_000
    assert cost.wallclock == pytest.approx(2.0)
    assert cost.calls is None
    # No card, or a card that recorded nothing, is unknown -- not a free diff.
    assert Cost.from_cards([]).known is False
    assert Cost.from_cards([_card("rule")]).known is False


def test_missing_cost_is_unknown_and_never_a_zero():
    empty = Cost()
    assert empty.known is False
    assert empty.to_dict()["tokens"] is None
    assert cost_efficiency(0.2, empty) is None
    assert cost_efficiency(0.2, Cost(tokens=0)) is None
    assert cost_status(None, 50.0) == "unknown"
    assert cost_status(10.0, None) == "unknown"


def test_efficiency_needs_a_positive_gain_and_known_units():
    cost = Cost(tokens=1_000)
    assert cost_efficiency(0.0, cost) is None
    assert cost_efficiency(-0.1, cost) is None
    assert cost_efficiency(0.1, Cost(usd=0.0)) is None
    assert cost_efficiency(0.1, cost, unit="usd") is None
    assert cost_efficiency(0.1, Cost(usd=0.02), unit="usd") == pytest.approx(5.0)
    with pytest.raises(ValueError, match="unit"):
        cost_efficiency(0.1, cost, unit="tokens")


def test_cost_status_is_the_three_way_read_the_report_promises():
    assert cost_status(60.0, 50.0) == "improved"
    assert cost_status(52.0, 50.0) == "neutral"
    assert cost_status(40.0, 50.0) == "regressed"
    # A non-positive reference has no scale to compare against.
    assert cost_status(60.0, 0.0) == "unknown"


def test_cost_refuses_negative_and_inconsistent_numbers():
    with pytest.raises(ValueError, match="tokens"):
        Cost(tokens=-1)
    with pytest.raises(ValueError, match="prompt_tokens"):
        Cost(prompt_tokens=-2)
    with pytest.raises(ValueError, match="wallclock"):
        Cost(wallclock=float("nan"))
    with pytest.raises(ValueError, match="inconsistent"):
        Cost(prompt_tokens=100, completion_tokens=50, tokens=200)


# -- the cost-aware acceptance option ---------------------------------------


def test_a_quality_gain_that_doubles_cost_is_refused():
    policy = CostPolicy(_AcceptAll(), reference_quality_per_cost=0.1)
    # +0.20 for 10k tokens is 0.02 per 1k: a fifth of the reference, not a win.
    decision = policy.accept(_ctx(cost=Cost(tokens=10_000)))
    assert decision.accept is False
    assert decision.category == "cost-regression"
    assert "0.02" in decision.detail and "0.1" in decision.detail
    assert decision.observed_delta == pytest.approx(0.2)
    assert decision.provenance["cost"]["tokens"] == 10_000
    assert decision.provenance["cost"]["status"] == "regressed"


def test_the_same_gain_at_a_fifth_of_the_cost_is_accepted():
    policy = CostPolicy(_AcceptAll(), reference_quality_per_cost=0.1)
    decision = policy.accept(_ctx(cost=Cost(tokens=1_000)))
    assert decision.accept is True
    assert decision.provenance["cost"]["status"] == "improved"
    assert decision.provenance["cost"]["quality_per_1k_tokens"] == \
        pytest.approx(0.2)


def test_a_required_cost_defers_when_the_evidence_has_none():
    policy = CostPolicy(_AcceptAll(), require_cost=True)
    decision = policy.accept(_ctx(cards=(), cost=None))
    assert decision.accept is False
    assert decision.defer is True
    assert decision.category == "cost-unknown"
    # Cost that cannot be priced (no gain, or no tokens) is unknown too.
    unpriced = policy.accept(_ctx(cards=(_card("rule"),), cost=None))
    assert unpriced.defer is True
    assert unpriced.category == "cost-unknown"


def test_an_optional_cost_keeps_the_quality_decision_and_says_unknown():
    policy = CostPolicy(_AcceptAll())
    decision = policy.accept(_ctx(cards=(), cost=None))
    assert decision.accept is True
    assert decision.provenance["cost"]["status"] == "unknown"


def test_cost_never_rescues_a_rejected_candidate():
    decision = CostPolicy(_RejectAll(),
                          reference_quality_per_cost=1.0).accept(
        _ctx(cost=Cost(tokens=1_000)))
    assert decision.accept is False
    assert decision.category == "no-improvement"


def test_the_policy_reads_the_cards_when_the_caller_supplies_no_cost_block():
    policy = CostPolicy(_AcceptAll(), reference_quality_per_cost=0.1)
    decision = policy.accept(_ctx(cards=(_card("rule", tokens=10_000),)))
    assert decision.accept is False
    assert decision.category == "cost-regression"
    assert decision.provenance["cost"]["tokens"] == 10_000


# -- the report -------------------------------------------------------------


def _row(*, accepted, gain=0.0, cost=None):
    return {"accepted": accepted, "gain": gain, "cost": cost}


def test_report_shows_cost_per_accepted_diff_and_per_point_of_gain():
    report = cost_report([
        _row(accepted=True, gain=0.2, cost={"calls": 6, "tokens": 3_000,
                                            "usd": 0.03}),
        _row(accepted=True, gain=0.1, cost={"calls": 2, "tokens": 1_000,
                                            "usd": 0.01}),
        _row(accepted=False, cost={"calls": 4, "tokens": 2_000, "usd": 0.02}),
    ], reference_tokens_per_point=30_000)
    assert isinstance(report, CostReport)
    assert report.decisions == 3 and report.accepted == 2
    assert report.calls == 12 and report.tokens == 6_000
    assert report.usd == pytest.approx(0.06)
    assert report.tokens_per_accepted == pytest.approx(3_000)
    assert report.calls_per_accepted == pytest.approx(6)
    assert report.usd_per_accepted == pytest.approx(0.03)
    # 6,000 tokens for 0.3 points of accepted gain.
    assert report.tokens_per_point == pytest.approx(20_000)
    assert report.usd_per_point == pytest.approx(0.2)
    # Cost per point is lower-better, so 20k against a 30k reference improves.
    assert report.cost_status == "improved"
    assert report.to_dict()["tokens_per_point"] == pytest.approx(20_000)


def test_report_never_silently_zeroes_missing_cost():
    report = cost_report([_row(accepted=True, gain=0.2),
                          _row(accepted=True, gain=0.1, cost={})])
    assert report.accepted == 2
    assert report.tokens is None and report.usd is None
    assert report.tokens_per_accepted is None
    assert report.tokens_per_point is None
    assert report.cost_status == "unknown"
    assert report.missing_cost == 2


def test_report_status_without_a_reference_is_unknown():
    report = cost_report([_row(accepted=True, gain=0.2,
                               cost={"tokens": 1_000})])
    assert report.tokens_per_point == pytest.approx(5_000)
    assert report.cost_status == "unknown"


# -- the promotion gate -----------------------------------------------------


def test_require_cost_off_keeps_the_previous_decision():
    assert promote(_promotion_request()).action == PromotionAction.PROMOTE


def test_require_cost_defers_when_the_request_carries_no_cost():
    decision = promote(_promotion_request(), PromotionRules(require_cost=True))
    assert decision.action == PromotionAction.DEFER
    assert decision.missing == ("cost",)


def test_require_cost_defers_an_unpriced_cost_block():
    decision = promote(_promotion_request(cost=Cost()),
                       PromotionRules(require_cost=True))
    assert decision.action == PromotionAction.DEFER
    assert "cost" in decision.missing[0]


def test_require_cost_promotes_when_a_cost_was_measured():
    cost = Cost(calls=3, prompt_tokens=1_000, completion_tokens=500,
                wallclock=2.5)
    decision = promote(_promotion_request(cost=cost),
                       PromotionRules(require_cost=True))
    assert decision.action == PromotionAction.PROMOTE
    assert decision.evidence["cost"]["tokens"] == 1_500


def test_a_partly_priced_report_never_understates_the_cost():
    """An unpriced accepted row must not read as a free gain (#945 review)."""
    report = cost_report([
        {"accepted": True, "gain": 0.2, "cost": {"tokens": 1000}},
        {"accepted": True, "gain": 0.1},
    ])

    # The partial totals stay visible, and the gap is counted.
    assert report.tokens == 1000
    assert report.accepted == 2
    assert report.missing_cost == 1
    # Every derived read is None: a partial numerator over the full denominator
    # is exactly the "looks cheaper than the evidence" failure this card exists
    # to prevent.
    assert report.tokens_per_accepted is None
    assert report.tokens_per_point is None
    assert report.cost_status == "unknown"


def test_an_unpriced_rejected_row_also_leaves_the_per_accepted_unknown():
    """Amortized spend covers every decision, so a silent rejected row counts."""
    report = cost_report([
        {"accepted": True, "gain": 0.2, "cost": {"tokens": 1000}},
        {"accepted": False},
    ])

    assert report.tokens == 1000
    assert report.missing_cost == 0, "only accepted rows carry missing_cost"
    assert report.tokens_per_accepted is None
    assert report.tokens_per_point is None


def test_a_priced_row_that_lacks_the_unit_never_enters_that_units_average():
    """A row priced in tokens only must not read as a free dollar gain."""
    report = cost_report([
        {"accepted": True, "gain": 0.2, "cost": {"tokens": 1000, "usd": 0.02}},
        {"accepted": True, "gain": 0.1, "cost": {"tokens": 1000}},
    ])

    # Both rows measured tokens, so the token average is real.
    assert report.tokens_per_accepted == 1000.0
    assert report.tokens_per_point == pytest.approx(2000 / 0.3)
    # Only one row measured dollars: $0.02 over two diffs would read as $0.01.
    assert report.usd == pytest.approx(0.02)
    assert report.usd_per_accepted is None
    assert report.usd_per_point is None
    # Every decision carried a cost block, so nothing is counted missing.
    assert report.missing_cost == 0


def test_a_wallclock_only_row_never_enters_the_token_average():
    """`Cost.from_cards` records tokens and wallclock but never calls, so a
    unit-complete row is normal and must not be read as free tokens."""
    report = cost_report([
        {"accepted": True, "gain": 0.2, "cost": {"tokens": 1000}},
        {"accepted": True, "gain": 0.1, "cost": {"wallclock": 1.5}},
    ])

    assert report.missing_cost == 0
    assert report.tokens == 1000
    assert report.wallclock == pytest.approx(1.5)
    # 1000 tokens over two accepted diffs would read as 500: cheaper than the
    # evidence, because the second diff never measured tokens at all.
    assert report.tokens_per_accepted is None
    assert report.tokens_per_point is None
    assert report.cost_status == "unknown"


def test_a_unit_every_decision_measured_keeps_its_average():
    """The per-unit rule is not "any gap blanks everything": a complete unit
    still reports, and only the incomplete ones go None."""
    report = cost_report([
        {"accepted": True, "gain": 0.2, "cost": {"tokens": 1000, "usd": 0.02}},
        {"accepted": True, "gain": 0.1, "cost": {"tokens": 3000, "usd": 0.06}},
        {"accepted": False, "cost": {"tokens": 2000, "usd": 0.04}},
    ])

    assert report.accepted == 2
    assert report.tokens == 6000
    assert report.tokens_per_accepted == pytest.approx(3000.0)
    assert report.tokens_per_point == pytest.approx(6000 / 0.3)
    assert report.usd_per_accepted == pytest.approx(0.06)
    assert report.calls_per_accepted is None, "no row measured calls"
