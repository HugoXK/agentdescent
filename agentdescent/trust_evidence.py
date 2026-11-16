"""Build one promotion bundle from the independent evidence modules.

`promotion` knows how to judge evidence, but a caller still has to assemble the
evaluation, canary, conformal, sequential, Goodhart, metamorphic, verifier and
calibration reports. This module is that assembly line. It turns paired
incumbent/candidate task scores into every report the promotion seam can use,
so the independent modules are connected instead of being entry points nobody
calls.

    evidence = build_trust_evidence(
        before_scores, after_scores,
        verifier=ensemble, candidate=candidate,
        calibration=(confidences, outcomes),
        proxy_gains=proxy, oracle_gains=oracle,
        metamorphic=suite, metamorphic_run=solver,
        metamorphic_tasks=tasks,
        contaminated=False, risk=0.2,
    )
    decision = promote(evidence.to_promotion_request("skill-1"),
                       PromotionRules(require_goodhart=True,
                                      require_verifier=True,
                                      require_calibration=True))

The builder does not decide promotion and does not re-run a gate. It only
computes the reports from the data the caller already has.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple

from .conformal import ConformalGate, ConformalReport
from .evalops import EvalResult
from .goodhart import GoodhartReport, detect_goodhart
from .metamorphic import MetamorphicReport, MetamorphicSuite
from .promotion import PromotionRequest
from .safety_controller import CanaryResult, canary
from .self_model import CalibrationReport, SelfModel
from .sequential import SequentialReport, sequential_test
from .stats_eval import (bootstrap_ci, calibrate_noise, is_significant,
                         paired_gain)
from .verifier_ensemble import EnsembleReport, VerifierEnsemble

__all__ = ["RunHealth", "TrustEvidence", "build_trust_evidence"]


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not bool")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _content_hash(before: Mapping[str, float], after: Mapping[str, float]) -> str:
    body = json.dumps(
        {"before": sorted((str(k), float(v)) for k, v in before.items()),
         "after": sorted((str(k), float(v)) for k, v in after.items())},
        sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


def _artifact_metadata(artifact_changed: Optional[bool],
                       metadata: dict) -> dict:
    """Metadata that records the artifact comparison, when there was one.

    The keys are omitted for a caller that did not compare artifacts, so the
    evidence of a bundle built before this field existed hashes the same.
    """
    if artifact_changed is not None:
        metadata["artifact_changed"] = artifact_changed
        metadata["noise_only"] = artifact_changed is False
    return metadata


@dataclass(frozen=True)
class RunHealth:
    """How much of a run produced a real answer (#993).

    ``failed_tasks`` never produced an answer, so they are not scored as zero:
    the gain is the mean over the tasks that answered. Above ``threshold`` the
    run fails its gate, because a run that mostly did not measure is not
    evidence of an improvement.
    """

    attempted: int
    failed_tasks: Tuple[str, ...] = ()
    threshold: float = 0.2

    def __post_init__(self) -> None:
        if isinstance(self.attempted, bool) or not isinstance(self.attempted, int):
            raise ValueError("run health attempted must be an int")
        if self.attempted < 1:
            raise ValueError("run health attempted must be at least 1")
        failed = tuple(str(task) for task in (self.failed_tasks or ()))
        if len(set(failed)) != len(failed):
            raise ValueError("run health failed_tasks must not repeat a task")
        if len(failed) > self.attempted:
            raise ValueError("run health failed_tasks exceeds attempted")
        threshold = _finite(self.threshold, "run health threshold")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("run health threshold must be in [0, 1]")
        object.__setattr__(self, "failed_tasks", failed)
        object.__setattr__(self, "threshold", threshold)

    @property
    def failed(self) -> int:
        return len(self.failed_tasks)

    @property
    def failure_rate(self) -> float:
        return self.failed / self.attempted

    @property
    def censored(self) -> bool:
        """True when the run is too broken to read as evidence."""
        return self.failure_rate > self.threshold

    def to_dict(self) -> dict:
        return {"attempted": self.attempted, "failed": self.failed,
                "failure_rate": self.failure_rate, "threshold": self.threshold,
                "failed_tasks": list(self.failed_tasks)}


def _run_health(value: Any) -> RunHealth:
    if isinstance(value, RunHealth):
        return value
    if not isinstance(value, Mapping):
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            value = to_dict()
    if not isinstance(value, Mapping):
        raise ValueError("run health must be a mapping or a RunHealth")
    allowed = {"attempted", "failed_tasks", "threshold", "failed",
               "failure_rate"}
    unknown = sorted(str(key) for key in set(value) - allowed)
    if unknown:
        raise ValueError(
            f"unknown run health field(s): {', '.join(unknown)}")
    if "attempted" not in value:
        raise ValueError("run health needs attempted")
    attempted = value["attempted"]
    if isinstance(attempted, bool) or not isinstance(attempted, int) \
            or attempted < 1:
        raise ValueError("run health attempted must be an int of at least 1")
    failed_tasks = tuple(str(task) for task in (value.get("failed_tasks") or ()))
    # ``to_dict`` emits the count and the rate, so reading them back is legal;
    # a count that disagrees with the task ids is not. Without this the caller
    # could hand ``failed: 14`` with no ids, have it rewritten to zero failures
    # and be told the run is healthy -- a silently rewritten number.
    if "failed" in value and value["failed"] != len(failed_tasks):
        raise ValueError(
            "run health failed count does not match failed_tasks")
    if "failure_rate" in value:
        rate = _finite(value["failure_rate"], "run health failure_rate")
        if not math.isclose(rate, len(failed_tasks) / attempted,
                            rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                "run health failure_rate does not match failed_tasks")
    return RunHealth(
        attempted=attempted,
        failed_tasks=failed_tasks,
        threshold=value.get("threshold", 0.2))


_ARTIFACT_NOTE_TEXT = ("artifact unchanged, so the eval delta is evaluation "
                       "noise, not learning")
#: The separator belongs to the composition, not to the sentence: a detail that
#: starts with the note (an empty original) has none, and a pattern that
#: required one would leave the second copy behind on the next rebuild.
_ARTIFACT_NOTE = re.compile(r"(?:;\s*)?" + re.escape(_ARTIFACT_NOTE_TEXT))
_HEALTH_NOTE = re.compile(r"(?:;\s*)?run health: .*?task\(s\)")


def _drop_failed_tasks(result: EvalResult, health: RunHealth) -> EvalResult:
    """Recompute the gate over the tasks that answered, not the failures."""
    failed = set(health.failed_tasks)
    answered = {task: delta for task, delta in result.per_task.items()
                if str(task) not in failed}
    n = len(answered)
    delta = (sum(answered.values()) / n) if n else 0.0
    interval = bootstrap_ci({task: 0.0 for task in answered}, answered)
    censored = health.censored or n == 0
    # ``replace`` on a bundle re-appends the note; strip the previous copy and
    # nothing else, so a note another field appended (the artifact one) stays.
    # The separator is optional in the pattern because the note can lead the
    # detail; ``strip`` drops the one the removal leaves behind.
    detail = _HEALTH_NOTE.sub("", result.detail).strip("; ")
    health_note = (f"run health: {health.failed} of "
                   f"{health.attempted} tasks failed at the provider or harness "
                   f"(rate {health.failure_rate:.2f} vs threshold "
                   f"{health.threshold:.2f}); gain is the mean over {n} answered "
                   f"task(s)")
    detail = f"{detail}; {health_note}" if detail else health_note
    return replace(result, n=n, delta=delta, ci=(interval.lo, interval.hi),
                   per_task=answered,
                   passed=result.passed and not censored, detail=detail)


@dataclass(frozen=True)
class TrustEvidence:
    """The reports one paired evaluation produced, ready for `promote()`."""

    eval_result: EvalResult
    canary: CanaryResult
    conformal: Optional[ConformalReport] = None
    sequential: Optional[SequentialReport] = None
    goodhart: Optional[GoodhartReport] = None
    metamorphic: Optional[MetamorphicReport] = None
    verifier: Optional[EnsembleReport] = None
    calibration: Optional[CalibrationReport] = None
    contaminated: Optional[bool] = None
    risk: Optional[float] = None
    approved: Optional[bool] = None
    #: Whether the compared artifacts differ byte-for-byte. ``None`` means the
    #: caller did not compare them, so the bundle keeps the behaviour it had
    #: before this field existed.
    artifact_changed: Optional[bool] = None
    run_health: Optional[RunHealth] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.contaminated is not None and not isinstance(self.contaminated, bool):
            raise TypeError("contaminated must be a bool or None")
        if self.approved is not None and not isinstance(self.approved, bool):
            raise TypeError("approved must be a bool or None")
        if self.artifact_changed is not None and not isinstance(
                self.artifact_changed, bool):
            raise TypeError("artifact_changed must be a bool or None")
        if self.artifact_changed is False:
            # Byte-identical before and after: any moved score is evaluation
            # noise, so it can neither be reported as gain nor pass an eval
            # gate. Zeroing here covers every construction path, including a
            # caller that builds the bundle directly from its own EvalResult.
            detail = _ARTIFACT_NOTE.sub(
                "", self.eval_result.detail).strip("; ")
            object.__setattr__(self, "eval_result", replace(
                self.eval_result, delta=0.0, passed=False,
                detail=(f"{detail}; {_ARTIFACT_NOTE_TEXT}" if detail
                        else _ARTIFACT_NOTE_TEXT)))
        if self.risk is not None:
            risk = _finite(self.risk, "risk")
            if not 0.0 <= risk <= 1.0:
                raise ValueError("risk must be in [0, 1]")
        metadata = dict(self.metadata or {})
        object.__setattr__(self, "metadata", metadata)
        health = self.run_health
        if health is None and metadata.get("run_health") is not None:
            health = _run_health(metadata["run_health"])
        elif health is not None:
            health = _run_health(health)
        if health is not None:
            # Every construction path gets this, ``dataclasses.replace`` too.
            object.__setattr__(self, "run_health", health)
            if metadata.get("run_health") != health.to_dict():
                metadata["run_health"] = health.to_dict()
            updated = _drop_failed_tasks(self.eval_result, health)
            if self.artifact_changed is False:
                updated = replace(updated, delta=0.0, passed=False)
            object.__setattr__(self, "eval_result", updated)

    @property
    def noise_only(self) -> bool:
        """True when the artifact is known to be byte-identical before and after."""
        return self.artifact_changed is False

    @property
    def gain(self) -> float:
        """The effect this bundle may report; zero when nothing changed on disk."""
        return 0.0 if self.noise_only else self.eval_result.delta

    @property
    def noise(self) -> Optional[Mapping[str, Any]]:
        """The baseline noise calibration, when the caller supplied repeats."""
        return self.metadata.get("noise")

    def to_promotion_request(self, artifact_id: str, *,
                             artifact_hash: Optional[str] = None,
                             proof: Optional[Any] = None,
                             admission: Optional[Any] = None) -> PromotionRequest:
        """A `PromotionRequest` carrying every report this bundle has."""
        metadata = dict(self.metadata)
        metadata.update({
            "goodhart": None if self.goodhart is None else asdict(self.goodhart),
            "metamorphic": (None if self.metamorphic is None
                            else asdict(self.metamorphic)),
            "verifier": (None if self.verifier is None
                         else self.verifier.to_dict()),
            "calibration": (None if self.calibration is None
                            else asdict(self.calibration)),
        })
        return PromotionRequest(
            artifact_id=artifact_id, artifact_hash=artifact_hash,
            eval_result=self.eval_result, contaminated=self.contaminated,
            conformal=self.conformal, sequential=self.sequential,
            canary=self.canary, proof=proof, admission=admission,
            risk=self.risk, approved=self.approved, goodhart=self.goodhart,
            metamorphic=self.metamorphic, verifier=self.verifier,
            calibration=self.calibration, metadata=metadata)

    def to_dict(self) -> dict:
        body = {
            "eval": self.eval_result.to_dict(),
            "canary": asdict(self.canary),
            "conformal": None if self.conformal is None else asdict(self.conformal),
            "sequential": None if self.sequential is None else asdict(self.sequential),
            "goodhart": None if self.goodhart is None else asdict(self.goodhart),
            "metamorphic": (None if self.metamorphic is None
                            else asdict(self.metamorphic)),
            "verifier": (None if self.verifier is None
                         else self.verifier.to_dict()),
            "calibration": (None if self.calibration is None
                            else asdict(self.calibration)),
            "contaminated": self.contaminated,
            "risk": self.risk,
            "approved": self.approved,
            "metadata": dict(self.metadata),
        }
        if self.artifact_changed is not None:
            body["artifact_changed"] = self.artifact_changed
            body["noise_only"] = self.noise_only
        if self.run_health is not None:
            body["run_health"] = self.run_health.to_dict()
        if self.noise is not None:
            body["noise"] = dict(self.noise)
        return body


def _noise_refusal_note(noise: Any, *, min_effect: float) -> str:
    """Name the actual reason a gain is refused as noise.

    ``distinguishable`` is false for three causes: too few baseline repeats to
    bound a floor, a measurable floor the gain does not clear, or a floor
    narrower than ``min_effect`` (the effect-size bar decides). Every branch
    keeps the phrase ``not distinguishable from noise``.
    """
    head = f"gain {noise.gain:+.3f} is not distinguishable from noise"
    if noise.repeats < 2:
        return (f"{head} (the noise floor cannot be estimated from "
                f"{noise.repeats} baseline repeat(s); at least 2 are needed)")
    lo, hi = noise.noise_floor
    half_width = (hi - lo) / 2.0
    if half_width < float(min_effect):
        return (f"{head} (gain does not exceed min_effect "
                f"{float(min_effect):.3f}; noise floor half-width is "
                f"{half_width:.3f})")
    return (f"{head} (gain does not exceed the noise floor: baseline mean "
            f"{noise.baseline_mean:+.3f} \u00b1 {half_width:.3f})")


def build_trust_evidence(
        before: Mapping[str, float], after: Mapping[str, float], *,
        eval_id: str = "paired", dataset_id: str = "paired", version: int = 1,
        verifier: Optional[VerifierEnsemble] = None,
        candidate: Any = None,
        calibration: Optional[Tuple[Iterable[float], Iterable[float]]] = None,
        sequential_deltas: Optional[Iterable[float]] = None,
        sequential_max_n: Optional[int] = None,
        proxy_gains: Optional[Sequence[float]] = None,
        oracle_gains: Optional[Sequence[float]] = None,
        metamorphic: Optional[MetamorphicSuite] = None,
        metamorphic_run: Optional[Callable[[Any], Any]] = None,
        metamorphic_tasks: Iterable[Any] = (),
        contaminated: Optional[bool] = None,
        risk: Optional[float] = None,
        approved: Optional[bool] = None,
        artifact_changed: Optional[bool] = None,
        alpha: float = 0.05,
        seed: int = 0,
        min_effect: float = 0.0,
        baseline_runs: Optional[Sequence[Mapping[str, float]]] = None,
        candidate_runs: Optional[Sequence[Mapping[str, float]]] = None,
        noise_repeats: int = 3,
) -> TrustEvidence:
    """Compute every report from paired task scores and optional side data."""
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise TypeError("before and after must be mappings")
    if not before or not after:
        raise ValueError("before and after must not be empty")
    alpha = _finite(alpha, "alpha")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if _finite(min_effect, "min_effect") < 0:
        raise ValueError("min_effect must be >= 0")
    if (proxy_gains is None) != (oracle_gains is None):
        raise ValueError("proxy_gains and oracle_gains must be supplied together")
    if metamorphic is not None and metamorphic_run is None:
        raise ValueError("metamorphic needs a run callable")
    if verifier is not None and candidate is None:
        raise ValueError("verifier needs a candidate")
    if artifact_changed is not None and not isinstance(artifact_changed, bool):
        raise TypeError("artifact_changed must be a bool or None")
    if baseline_runs is None and candidate_runs is not None:
        raise ValueError("candidate_runs needs baseline_runs")
    if baseline_runs is not None:
        if (not isinstance(baseline_runs, Sequence)
                or isinstance(baseline_runs, (str, bytes)) or not baseline_runs):
            raise ValueError("baseline_runs must be a non-empty sequence")
        if candidate_runs is not None and (
                not isinstance(candidate_runs, Sequence)
                or isinstance(candidate_runs, (str, bytes))
                or not candidate_runs):
            raise ValueError("candidate_runs must be a non-empty sequence")

    deltas = paired_gain(before, after)
    if not deltas:
        raise ValueError("before and after have no task keys in common")
    bootstrap = bootstrap_ci(before, after, alpha=alpha, seed=seed)
    common = sorted(before.keys() & after.keys(), key=str)
    before_values = [float(before[key]) for key in common]
    after_values = [float(after[key]) for key in common]
    per_task = {str(key): float(after[key]) - float(before[key])
                for key in common}
    eval_result = EvalResult(
        eval_id=eval_id, dataset_id=dataset_id, version=version,
        content_hash=_content_hash(before, after), n=bootstrap.n,
        score=sum(after_values) / len(after_values),
        baseline=sum(before_values) / len(before_values),
        delta=bootstrap.mean, ci=(bootstrap.lo, bootstrap.hi),
        passed=is_significant(bootstrap, min_effect=min_effect),
        cost=0.0, per_task=per_task,
        detail=(f"bootstrap n={bootstrap.n}, "
                f"prob_positive={bootstrap.prob_positive:.3f}"))

    noise = None
    if baseline_runs is not None:
        groups = {"baseline": [dict(run) for run in baseline_runs],
                  "candidate": [dict(run) for run in (
                      candidate_runs if candidate_runs is not None else [after])]}
        noise = calibrate_noise(
            groups, expected_repeats=noise_repeats, alpha=alpha, seed=seed,
            min_effect=min_effect)
        if not noise.distinguishable:
            note = _noise_refusal_note(noise, min_effect=min_effect)
            detail = (f"{eval_result.detail}; {note}"
                      if eval_result.detail else note)
            eval_result = replace(eval_result, passed=False, detail=detail)

    canary_result = canary(before, after, min_effect=min_effect, alpha=alpha)
    conformal = ConformalGate(alpha=alpha).fit(deltas).decide()
    stream = sequential_test(
        deltas if sequential_deltas is None else sequential_deltas,
        alpha=alpha, max_n=sequential_max_n)

    goodhart = None
    if proxy_gains is not None and oracle_gains is not None:
        goodhart = detect_goodhart(proxy_gains, oracle_gains)

    metamorphic_report = None
    if metamorphic is not None:
        metamorphic_report = metamorphic.evaluate(
            metamorphic_run, metamorphic_tasks)

    verifier_report = None
    if verifier is not None:
        verifier_report = verifier.evaluate(candidate)

    calibration_report = None
    if calibration is not None:
        confidences, outcomes = calibration
        calibration_report = SelfModel().fit(confidences, outcomes)

    metadata = _artifact_metadata(
        artifact_changed,
        {"before_tasks": len(before), "after_tasks": len(after),
         "common_tasks": len(deltas)})
    if noise is not None:
        metadata["noise"] = noise.to_dict()
    return TrustEvidence(
        eval_result=eval_result, canary=canary_result, conformal=conformal,
        sequential=stream, goodhart=goodhart, metamorphic=metamorphic_report,
        verifier=verifier_report, calibration=calibration_report,
        contaminated=contaminated, risk=risk, approved=approved,
        artifact_changed=artifact_changed, metadata=metadata)
