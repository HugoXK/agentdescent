"""Baseline noise calibration must not sell run-to-run noise as a gain."""

from __future__ import annotations

import pytest

from agentdescent.stats_eval import (NoiseCalibration, VarianceDecomposition,
                                     calibrate_noise, decompose_variance)


def _flat(value=0.5, tasks=8):
    return {f"t{i}": value for i in range(tasks)}


def _runs(value, repeats=3, tasks=8):
    return [_flat(value, tasks) for _ in range(repeats)]


def _width(report):
    lo, hi = report.noise_floor
    return hi - lo


def test_a_flat_repeat_is_not_distinguishable_from_noise():
    for seed in range(3):
        report = calibrate_noise({"baseline": _runs(0.5)}, seed=seed)
        assert isinstance(report, NoiseCalibration)
        assert report.noise_floor == pytest.approx((0.5, 0.5))
        assert report.gain == pytest.approx(0.0)
        assert report.distinguishable is False
        assert report.verdict == "not distinguishable from noise"
        assert report.variance["model"] == pytest.approx(0.0)


def test_a_strong_gain_clears_the_noise_floor():
    for seed in range(3):
        report = calibrate_noise(
            {"baseline": _runs(0.2), "candidate": _runs(0.8)}, seed=seed)
        assert report.gain == pytest.approx(0.6)
        assert report.distinguishable is True
        assert report.verdict == "distinguishable from noise"
        # zero-spread floor: the ratio is undefined, not a 6e+08 epsilon artefact
        assert report.gain_over_noise == 0.0


def test_high_run_to_run_variance_widens_the_floor_and_warns():
    for seed in range(3):
        steady = calibrate_noise({"baseline": _runs(0.5)}, seed=seed)
        noisy_runs = [_flat(0.2), _flat(0.5), _flat(0.8)]
        noisy = calibrate_noise(
            {"baseline": noisy_runs, "candidate": _runs(0.55)}, seed=seed)
        assert noisy.warning and "run-to-run" in noisy.warning
        assert _width(noisy) > _width(steady)
        assert noisy.variance["run"] > noisy.variance["task"]
        assert noisy.gain == pytest.approx(0.05)
        assert noisy.distinguishable is False


def test_variance_decomposition_splits_task_model_and_run():
    def run(task_shift, run_shift):
        return {f"t{i}": 0.5 + task_shift * i + run_shift
                for i in range(4)}

    groups = {
        "model-a": [run(0.1, 0.0), run(0.1, 0.2)],
        "model-b": [run(0.1, 0.4), run(0.1, 0.6)],
    }
    report = decompose_variance(groups)
    assert isinstance(report, VarianceDecomposition)
    assert report.task > 0 and report.model > 0 and report.run > 0
    assert report.total > 0
    shares = report.to_dict()
    assert sum(shares.values()) == pytest.approx(1.0)
    assert report.shares == pytest.approx(shares)


def test_one_repeat_is_refused_as_evidence_not_trusted_as_zero_noise():
    report = calibrate_noise({"baseline": _runs(0.5, repeats=1)}, seed=0)
    assert report.repeats == 1
    assert report.distinguishable is False
    assert report.warning and "repeat" in report.warning


def test_calibration_validates_its_inputs():
    with pytest.raises(ValueError, match="alpha"):
        calibrate_noise({"baseline": _runs(0.5)}, alpha=1.0)
    with pytest.raises(ValueError, match="non-empty"):
        calibrate_noise({})
    with pytest.raises(ValueError, match="min_effect"):
        calibrate_noise({"baseline": _runs(0.5)}, min_effect=float("nan"))


@pytest.mark.parametrize("baseline,candidate,min_effect,distinguishable", [
    ([_flat(0.5)], _runs(0.8), 0.0, False),          # one repeat: no floor
    (_runs(0.5), _runs(0.52), 0.5, False),           # zero spread, below min_effect
    (_runs(0.2), _runs(0.8), 0.0, True),             # zero spread, passes
])
def test_gain_over_noise_is_zero_when_the_floor_is_undefined(
        baseline, candidate, min_effect, distinguishable):
    report = calibrate_noise({"baseline": baseline, "candidate": candidate},
                             min_effect=min_effect)
    assert report.gain_over_noise == 0.0
    assert report.distinguishable is distinguishable


def test_gain_over_noise_keeps_the_ratio_on_a_measurable_floor():
    report = calibrate_noise(
        {"baseline": [_flat(0.3), _flat(0.5), _flat(0.7)],
         "candidate": _runs(0.55)}, seed=0)
    lo, hi = report.noise_floor
    assert hi > lo
    assert report.gain_over_noise == pytest.approx(
        report.gain / ((hi - lo) / 2.0))
    assert report.distinguishable is False
