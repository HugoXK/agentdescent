"""A gain inside the baseline noise floor is not promotion evidence."""

from __future__ import annotations

import pytest

from agentdescent.promotion import PromotionAction, promote
from agentdescent.trust_evidence import build_trust_evidence


def _flat(value=0.5, tasks=8):
    return {f"t{i}": value for i in range(tasks)}


def _runs(value, repeats=3, tasks=8):
    return [_flat(value, tasks) for _ in range(repeats)]


def _evidence(before_value, after_value, baseline_values, candidate_values):
    return build_trust_evidence(
        _flat(before_value), _flat(after_value),
        contaminated=False, risk=0.1,
        baseline_runs=[_flat(value) for value in baseline_values],
        candidate_runs=[_flat(value) for value in candidate_values])


def test_flat_repeats_are_reported_as_not_distinguishable_and_rejected():
    evidence = _evidence(0.5, 0.5, [0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
    noise = evidence.metadata["noise"]
    assert noise["distinguishable"] is False
    assert evidence.eval_result.passed is False
    assert "not distinguishable from noise" in evidence.eval_result.detail
    decision = promote(evidence.to_promotion_request("candidate"))
    assert decision.action == PromotionAction.REJECT


def test_a_gain_inside_the_noise_floor_is_not_evidence():
    evidence = _evidence(0.5, 0.55, [0.3, 0.5, 0.7], [0.55, 0.55, 0.55])
    noise = evidence.metadata["noise"]
    assert noise["gain"] == pytest.approx(0.05)
    assert noise["distinguishable"] is False
    assert evidence.eval_result.passed is False
    assert "not distinguishable from noise" in evidence.eval_result.detail


def test_a_strong_gain_clears_the_noise_floor_and_stays_promotable():
    evidence = _evidence(0.2, 0.8, [0.2, 0.2, 0.2], [0.8, 0.8, 0.8])
    noise = evidence.metadata["noise"]
    assert noise["distinguishable"] is True
    assert evidence.eval_result.passed is True
    assert evidence.eval_result.delta == pytest.approx(0.6)
    assert "not distinguishable from noise" not in evidence.eval_result.detail


def test_no_repeats_keeps_the_previous_behaviour():
    evidence = build_trust_evidence(
        _flat(0.2), _flat(0.8), contaminated=False, risk=0.1)
    assert "noise" not in evidence.metadata
    assert evidence.eval_result.passed is True


def test_one_baseline_repeat_names_the_repeat_count():
    evidence = _evidence(0.5, 0.8, [0.5], [0.8])
    detail = evidence.eval_result.detail
    assert "not distinguishable from noise" in detail
    assert "1 baseline repeat(s)" in detail
    assert "noise floor [" not in detail
    assert evidence.metadata["noise"]["gain_over_noise"] == 0.0


def test_zero_spread_below_min_effect_names_min_effect():
    evidence = build_trust_evidence(
        _flat(0.5), _flat(0.52), contaminated=False, risk=0.1,
        min_effect=0.5, baseline_runs=_runs(0.5), candidate_runs=_runs(0.52))
    detail = evidence.eval_result.detail
    assert "not distinguishable from noise" in detail
    assert "min_effect 0.500" in detail


def test_a_floor_refusal_prints_a_band_around_the_baseline_mean():
    evidence = _evidence(0.5, 0.55, [0.3, 0.5, 0.7], [0.55, 0.55, 0.55])
    detail = evidence.eval_result.detail
    assert "not distinguishable from noise" in detail
    assert "baseline mean +0.500 \u00b1" in detail


def test_a_passing_zero_spread_gain_has_no_note_and_no_fake_ratio():
    evidence = _evidence(0.2, 0.8, [0.2, 0.2, 0.2], [0.8, 0.8, 0.8])
    assert "not distinguishable" not in evidence.eval_result.detail
    assert evidence.metadata["noise"]["gain_over_noise"] == 0.0
