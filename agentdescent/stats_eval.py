"""Statistical and contamination checks for an RSI adoption decision.

A point-estimate rule ("the mean gain is positive") adopts noise: with a small
held-out set a candidate can win by one lucky task. This module gives the
acceptance/report layers the two numbers a product needs:

* a **paired bootstrap confidence interval** on the per-task gain and the
  probability that the true gain is positive;
* a **contamination overlap** between training and validation text, because a
  leaked example makes every confidence interval meaningless.

No dependencies beyond the standard library; the bootstrap is seeded, so a
report is reproducible.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = ["BootstrapResult", "ContaminationReport", "NoiseCalibration",
           "VarianceDecomposition", "bootstrap_ci", "calibrate_noise",
           "contamination_overlap", "decompose_variance", "is_significant",
           "paired_gain"]


@dataclass(frozen=True)
class BootstrapResult:
    """A paired bootstrap of per-task gains."""

    mean: float
    lo: float
    hi: float
    prob_positive: float
    n: int
    alpha: float


def paired_gain(before: Mapping[str, float],
                after: Mapping[str, float]) -> List[float]:
    """Per-task ``after - before`` over the keys present in both sides.

    Keys are visited in a stable order so a seeded bootstrap cannot depend on
    ``PYTHONHASHSEED``. Non-finite scores are refused: a NaN would otherwise
    make the interval depend on whichever comparison it happened to hit.
    """
    diffs = []
    for key in sorted(before.keys() & after.keys(), key=str):
        try:
            before_value = float(before[key])
            after_value = float(after[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"task {key!r} has a non-numeric score") from exc
        if not math.isfinite(before_value) or not math.isfinite(after_value):
            raise ValueError(f"task {key!r} has a non-finite score")
        diffs.append(after_value - before_value)
    return diffs


def bootstrap_ci(before: Mapping[str, float], after: Mapping[str, float], *,
                 n: int = 2000, alpha: float = 0.05,
                 seed: int = 0) -> BootstrapResult:
    """Bootstrap the mean paired gain, ``after - before``.

    Resampling is over tasks. ``prob_positive`` is the share of resampled means
    above zero (a one-sided read); the interval is the central ``1-alpha`` one.
    Fewer than two paired tasks gives a zero-width interval at the mean -- the
    caller should treat that as "not enough evidence", not as significance.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if n < 1:
        raise ValueError("n must be >= 1")
    diffs = paired_gain(before, after)
    if not diffs:
        return BootstrapResult(0.0, 0.0, 0.0, 0.0, 0, alpha)
    mean = sum(diffs) / len(diffs)
    if len(diffs) == 1:
        # One pair cannot estimate a distribution. 0.5 says "no evidence"
        # rather than a 100% positive share.
        return BootstrapResult(mean, mean, mean, 0.5, 1, alpha)
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        sample = [diffs[rng.randrange(len(diffs))] for _ in range(len(diffs))]
        means.append(sum(sample) / len(diffs))
    means.sort()
    # Both ends floor, so the interval is very slightly asymmetric. That is
    # intentional: the bootstrap distribution is discrete.
    lo = means[int((alpha / 2) * (n - 1))]
    hi = means[int((1 - alpha / 2) * (n - 1))]
    positive = sum(1 for value in means if value > 0.0) / n
    return BootstrapResult(mean, lo, hi, positive, len(diffs), alpha)


def is_significant(result: BootstrapResult, *,
                   min_effect: float = 0.0,
                   alpha: Optional[float] = None) -> bool:
    """Whether the lower bound clears ``min_effect`` and the interval is usable.

    ``alpha`` defaults to the interval's own alpha. Passing a different value is
    refused rather than silently returning ``False``: a caller that computed the
    interval at 0.10 and tests at 0.05 has a bug, not a non-significant result.
    """
    if (isinstance(min_effect, bool)
            or not isinstance(min_effect, (int, float))
            or not math.isfinite(float(min_effect))):
        raise ValueError("min_effect must be a finite number")
    if alpha is not None and alpha != result.alpha:
        raise ValueError(
            f"alpha {alpha} does not match the interval's alpha {result.alpha}")
    return result.n >= 2 and result.lo > min_effect


@dataclass(frozen=True)
class VarianceDecomposition:
    """A main-effects split of score variance into task, model and run.

    ``task``, ``model``, ``run`` and ``residual`` are variances in score-squared
    units; ``residual`` holds interactions and measurement error. ``total`` is
    the observed variance. For a balanced grid the four components add up to
    ``total``; unbalanced inputs are clamped, so ``shares`` still sums to one.
    """

    task: float
    model: float
    run: float
    residual: float
    total: float

    @property
    def shares(self) -> Dict[str, float]:
        if self.total <= 0.0:
            return {"task": 0.0, "model": 0.0, "run": 0.0, "residual": 0.0}
        return {"task": self.task / self.total,
                "model": self.model / self.total,
                "run": self.run / self.total,
                "residual": self.residual / self.total}

    def to_dict(self) -> Dict[str, float]:
        return self.shares


def _observations(observations: Mapping[str, Sequence[Mapping[str, float]]]
                  ) -> Tuple[List[Tuple[str, str, Any, float]], Dict[str, float]]:
    """Validate nested model -> run -> task scores and read their means."""
    if not isinstance(observations, Mapping) or not observations:
        raise ValueError("observations must be a non-empty mapping")
    records: List[Tuple[str, str, Any, float]] = []
    task_sums: Dict[Any, float] = {}
    task_counts: Dict[Any, int] = {}
    model_sums: Dict[str, float] = {}
    model_counts: Dict[str, int] = {}
    run_means: Dict[Tuple[str, int], float] = {}
    run_counts: Dict[Tuple[str, int], int] = {}
    for model, runs in observations.items():
        model_name = str(model)
        if (not isinstance(runs, Sequence) or isinstance(runs, (str, bytes))
                or not runs):
            raise ValueError(f"model {model_name!r} needs a non-empty run list")
        for run_index, run in enumerate(runs):
            if not isinstance(run, Mapping) or not run:
                raise ValueError(
                    f"model {model_name!r} run {run_index} must be a non-empty map")
            for task, score in run.items():
                try:
                    value = float(score)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"task {task!r} has a non-numeric score") from exc
                if not math.isfinite(value):
                    raise ValueError(f"task {task!r} has a non-finite score")
                records.append((model_name, str(run_index), task, value))
                task_sums[task] = task_sums.get(task, 0.0) + value
                task_counts[task] = task_counts.get(task, 0) + 1
                model_sums[model_name] = model_sums.get(model_name, 0.0) + value
                model_counts[model_name] = model_counts.get(model_name, 0) + 1
                key = (model_name, run_index)
                run_means[key] = run_means.get(key, 0.0) + value
                run_counts[key] = run_counts.get(key, 0) + 1
    for key, count in run_counts.items():
        run_means[key] /= count
    model_means = {name: model_sums[name] / model_counts[name]
                   for name in model_sums}
    return records, {
        "task_sums": task_sums, "task_counts": task_counts,
        "model_means": model_means, "model_counts": model_counts,
        "run_means": run_means, "run_counts": run_counts,
    }


def decompose_variance(
    observations: Mapping[str, Sequence[Mapping[str, float]]]
) -> VarianceDecomposition:
    """Split score variance into task, model and run components.

    ``observations`` is ``{model: [run, ...]}`` where each run maps task id to
    score. The estimator is a main-effects ANOVA: model and task effects plus
    run nested inside model; everything left over is the residual. It needs no
    statistics package and is deterministic.
    """
    records, stats = _observations(observations)
    total = sum(value for _, _, _, value in records)
    count = len(records)
    grand = total / count
    task_sums = stats["task_sums"]
    task_counts = stats["task_counts"]
    model_means = stats["model_means"]
    model_counts = stats["model_counts"]
    run_means = stats["run_means"]
    run_counts = stats["run_counts"]

    ss_total = sum((value - grand) ** 2 for _, _, _, value in records)
    ss_model = sum(model_counts[name] * (mean - grand) ** 2
                   for name, mean in model_means.items())
    ss_task = sum(task_counts[task] * (task_sums[task] / task_counts[task]
                                       - grand) ** 2
                  for task in task_sums)
    ss_run = 0.0
    for (model, run_index), mean in run_means.items():
        ss_run += run_counts[(model, run_index)] * (
            mean - model_means[model]) ** 2
    ss_resid = ss_total - ss_model - ss_task - ss_run
    # Unbalanced grids can make main effects overlap. Clamp instead of reporting
    # a negative share, and renormalise the denominator so shares still sum to 1.
    if ss_resid < 0.0:
        ss_resid = 0.0
    component_sum = ss_model + ss_task + ss_run + ss_resid
    denominator = max(ss_total, component_sum)
    if denominator <= 0.0:
        return VarianceDecomposition(0.0, 0.0, 0.0, 0.0, 0.0)
    return VarianceDecomposition(
        task=ss_task / count, model=ss_model / count, run=ss_run / count,
        residual=ss_resid / count, total=denominator / count)


def _interval(values: Sequence[float], *, alpha: float, seed: int,
              draws: int = 2000) -> Tuple[float, float]:
    """Seeded bootstrap interval of the mean, matching ``bootstrap_ci``."""
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return float(values[0]), float(values[0])
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(draws):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int((alpha / 2) * (draws - 1))]
    hi = means[int((1 - alpha / 2) * (draws - 1))]
    return lo, hi


@dataclass(frozen=True)
class NoiseCalibration:
    """What repeated baseline runs say about the smallest readable gain.

    ``noise_floor`` is a seeded 95% interval of the repeated baseline's mean
    score. ``variance`` is the task/model/run share split from
    :func:`decompose_variance`. A gain is ``distinguishable`` only when it is
    larger than both the floor's half-width and ``min_effect``; otherwise it is
    noise, not promotion evidence.

    ``gain_over_noise`` is the gain divided by the floor's half-width. It is
    ``0.0`` when the gain is not positive and also when the ratio is undefined:
    fewer than 2 baseline repeats bound no floor, and a zero-spread baseline has
    a zero half-width. ``0.0`` there means "undefined", not "no signal".
    """

    noise_floor: Tuple[float, float]
    variance: Dict[str, float]
    gain_over_noise: float
    distinguishable: bool
    gain: float = 0.0
    baseline_mean: float = 0.0
    repeats: int = 0
    alpha: float = 0.05
    warning: Optional[str] = None
    total_variance: float = 0.0

    @property
    def verdict(self) -> str:
        return ("distinguishable from noise" if self.distinguishable
                else "not distinguishable from noise")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "noise_floor": list(self.noise_floor),
            "variance": dict(self.variance),
            "gain_over_noise": self.gain_over_noise,
            "distinguishable": self.distinguishable,
            "gain": self.gain,
            "baseline_mean": self.baseline_mean,
            "repeats": self.repeats,
            "alpha": self.alpha,
            "warning": self.warning,
            "total_variance": self.total_variance,
            "verdict": self.verdict,
        }


def calibrate_noise(
    groups: Mapping[str, Sequence[Mapping[str, float]]], *,
    baseline: str = "baseline", candidate: Optional[str] = "candidate",
    expected_repeats: int = 3, alpha: float = 0.05, seed: int = 0,
    min_effect: float = 0.0, warning_width: float = 0.1,
) -> NoiseCalibration:
    """Calibrate the baseline noise floor from repeated runs.

    ``groups`` is ``{label: [run, ...]}``. The ``baseline`` label supplies the
    repeats that define the floor; when ``candidate`` is present its mean is
    compared with the baseline. ``expected_repeats`` (default 3) is the count
    below which the floor is reported as too thin to trust. A run-to-run spread
    wider than ``warning_width`` (or dominating the variance split) adds a
    warning: that is the case where a small gain cannot be read.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if isinstance(expected_repeats, bool) or not isinstance(expected_repeats, int) \
            or expected_repeats < 1:
        raise ValueError("expected_repeats must be an int >= 1")
    if isinstance(min_effect, bool) or not isinstance(min_effect, (int, float)) \
            or not math.isfinite(float(min_effect)) or float(min_effect) < 0.0:
        raise ValueError("min_effect must be a finite number >= 0")
    if isinstance(warning_width, bool) or not isinstance(
            warning_width, (int, float)) or not math.isfinite(
                float(warning_width)) or float(warning_width) < 0.0:
        raise ValueError("warning_width must be a finite number >= 0")
    if not isinstance(groups, Mapping) or not groups:
        raise ValueError("groups must be a non-empty mapping")
    if baseline not in groups:
        raise ValueError(f"groups must contain the baseline {baseline!r}")
    baseline_runs = list(groups[baseline])
    if not baseline_runs:
        raise ValueError(f"baseline {baseline!r} has no runs")

    records, _ = _observations(groups)
    baseline_values = [value for model, _, _, value in records
                       if model == baseline]
    baseline_mean = sum(baseline_values) / len(baseline_values)
    run_means = []
    for run in baseline_runs:
        values = [float(value) for value in run.values()]
        run_means.append(sum(values) / len(values))
    lo, hi = _interval(run_means, alpha=alpha, seed=seed)
    width = hi - lo
    half_width = width / 2.0

    candidate_mean = None
    if candidate is not None and candidate in groups:
        candidate_values = [value for model, _, _, value in records
                            if model == candidate]
        if candidate_values:
            candidate_mean = sum(candidate_values) / len(candidate_values)
    gain = 0.0 if candidate_mean is None else candidate_mean - baseline_mean
    # The ratio is undefined without a measurable floor (fewer than 2
    # repeats, or zero spread); report 0.0 rather than divide by an epsilon.
    gain_over_noise = (0.0 if gain <= 0.0 or len(baseline_runs) < 2
                       or half_width <= 0.0 else gain / half_width)
    # A gain exactly at the floor edge is still noise; the epsilon keeps a
    # floating-point representation of the edge from flipping the verdict.
    bar = max(half_width, float(min_effect))
    distinguishable = (len(baseline_runs) >= 2 and gain > 0.0
                       and gain > bar + 1e-12)

    decomposition = decompose_variance(groups)
    warnings = []
    if len(baseline_runs) < expected_repeats:
        warnings.append(
            f"only {len(baseline_runs)} baseline repeat(s); "
            f"{expected_repeats} are needed for a stable noise floor")
    if width > warning_width:
        warnings.append(
            f"baseline noise floor is wide ({width:.3f}); high run-to-run "
            "variance makes a small gain unreadable")
    if decomposition.shares["run"] >= 0.5 and decomposition.total > 0.0:
        warnings.append("run-to-run variance dominates the baseline")
    return NoiseCalibration(
        noise_floor=(lo, hi), variance=decomposition.shares,
        gain_over_noise=gain_over_noise, distinguishable=distinguishable,
        gain=gain, baseline_mean=baseline_mean, repeats=len(baseline_runs),
        alpha=alpha, warning="; ".join(warnings) if warnings else None,
        total_variance=decomposition.total)


@dataclass(frozen=True)
class ContaminationReport:
    """How much of the validation text appears in the training text.

    ``overlap`` is ``None`` when there were no n-grams to check (empty/short
    validation text). That is deliberately not ``0.0``: "we could not screen
    this" is not "this is clean". ``exact_duplicates`` counts normalized
    validation examples that also occur verbatim in training, whatever their
    length, so a two-word or CJK duplicate is still visible.
    """

    overlap: Optional[float]
    shared: Tuple[str, ...] = ()
    held_out_grams: int = 0
    exact_duplicates: int = 0
    examples: Tuple[str, ...] = ()


def _normalize(text: Any) -> str:
    return " ".join(str(text).casefold().split())


#: Split CJK characters so a short Chinese/Japanese sentence has tokens even
#: though it has no spaces.
_CJK = r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]"


def _word_grams(normalized: str, n: int) -> List[str]:
    split_cjk = re.sub(f"({_CJK})", r" \1 ", normalized)
    words = re.findall(r"\w+", split_cjk, re.UNICODE)
    return [" ".join(words[i:i + n])
            for i in range(max(0, len(words) - n + 1))]


def _char_grams(normalized: str, n: int) -> List[str]:
    chars = re.sub(r"\s+", "", normalized)
    return [chars[i:i + n] for i in range(max(0, len(chars) - n + 1))]


def _val_grams(text: str, n: int) -> Tuple[str, List[str]]:
    """Word grams when the validation text has enough words, else char grams.

    Training indexes both kinds; a short validation item is compared with the
    same kind it emitted. Comparing char grams only against word grams made a
    short item embedded in a longer prompt read as clean.
    """
    normalized = _normalize(text)
    words = _word_grams(normalized, n)
    if words:
        return "word", words
    return "char", _char_grams(normalized, n)


def contamination_overlap(train_texts: Sequence[str], val_texts: Sequence[str],
                          *, n: int = 5) -> ContaminationReport:
    """Fraction of validation n-grams that also occur in the training text.

    ``n=5`` is a word n-gram; exact duplicate examples produce an overlap of
    1.0. ``examples`` lists a few shared grams so a report can show the leak
    without printing the whole corpus. A low overlap is not proof of no
    contamination -- paraphrase and embeddings are not covered -- but a high one
    is a hard stop.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    train_texts = [text for text in train_texts if _normalize(text)]
    val_texts = [text for text in val_texts if _normalize(text)]
    train_examples = {_normalize(text) for text in train_texts}
    exact_duplicates = sum(
        1 for text in val_texts if _normalize(text) in train_examples)
    duplicate_fraction = (exact_duplicates / len(val_texts)
                          if val_texts else 0.0)
    train = {"word": Counter(), "char": Counter()}
    for text in train_texts:
        normalized = _normalize(text)
        train["word"].update(_word_grams(normalized, n))
        train["char"].update(_char_grams(normalized, n))
    val = {"word": Counter(), "char": Counter()}
    for text in val_texts:
        mode, grams = _val_grams(text, n)
        val[mode].update(grams)
    total = sum(sum(counter.values()) for counter in val.values())
    if total == 0:
        return ContaminationReport(
            overlap=(duplicate_fraction if duplicate_fraction else None),
            held_out_grams=0,
            exact_duplicates=exact_duplicates,
            examples=tuple(sorted(train_examples & {
                _normalize(text) for text in val_texts})[:5]))
    shared = []
    leaked = 0
    for mode in ("word", "char"):
        for gram, count in val[mode].items():
            if train[mode].get(gram):
                shared.append(gram)
                leaked += count
    overlap = max(leaked / total, duplicate_fraction)
    return ContaminationReport(
        overlap=overlap,
        shared=tuple(sorted(shared)),
        held_out_grams=total,
        exact_duplicates=exact_duplicates,
        examples=tuple(sorted(shared)[:5]))
