"""A run that mostly failed is not evidence of a promotion (#993).

A crashed call lands as a scored ``0``, so a run in which a third of the tasks
never answered could still hand a clean gain to the promoter. The bundle
carries a ``RunHealth`` record instead: the gain is the mean over the tasks that
answered and above the threshold the gate fails. Without health data the bundle
keeps today's keys and hash.
"""

import hashlib
import json
from dataclasses import replace

import pytest

from agentdescent.promotion import PromotionAction, PromotionRules, promote
from agentdescent.trust_evidence import build_trust_evidence


TASKS = 40
#: sha256 of the default bundle's JSON at the base commit: keys or values move, it breaks.
DEFAULT_BUNDLE_SHA256 = (
    "84b1e05a76f0c2751520b60646b62fe95e07c7cd7215aaaf6cc04d3231c920af")


def _scores(failed=0, n=TASKS):
    """``after`` gives the last ``failed`` tasks no gain: a zeroed crash."""
    before = {f"t{i}": 0.5 for i in range(n)}
    after = {f"t{i}": 1.0 if i < n - failed else 0.5 for i in range(n)}
    return before, after


def _raw(failed=0):
    return build_trust_evidence(*_scores(failed), contaminated=False,
                                risk=0.1, approved=True)


def _failed_ids(count, n=TASKS):
    return [f"t{i}" for i in range(n - count, n)]


def _evidence(failed_tasks=(), **extra):
    record = {"attempted": TASKS, "failed_tasks": list(failed_tasks)}
    record.update(extra)
    return replace(_raw(len(record["failed_tasks"])),
                   metadata={"run_health": record})


def _decision(failed_tasks=(), **extra):
    evidence = _evidence(failed_tasks=failed_tasks, **extra)
    return promote(evidence.to_promotion_request("skill-1"), PromotionRules())


def test_a_run_above_the_failure_threshold_cannot_promote():
    decision = _decision(failed_tasks=_failed_ids(14))
    reasons = " ".join(decision.reasons)

    assert decision.action != PromotionAction.PROMOTE
    assert "run health" in reasons
    assert "14 of 40" in reasons


def test_a_run_at_or_below_the_threshold_still_promotes():
    decision = _decision(failed_tasks=_failed_ids(1))

    assert decision.action == PromotionAction.PROMOTE
    assert not any("run health" in reason for reason in decision.reasons)


def test_failed_tasks_are_not_folded_in_as_zeroes():
    evidence = _evidence(failed_tasks=_failed_ids(14))
    request = evidence.to_promotion_request("skill-1")

    # The 14 zero-delta failures are dropped: 0.5 over the 26 answered, not
    # the 0.325 their zeroes would produce.
    assert evidence.eval_result.delta == pytest.approx(0.5)
    assert evidence.eval_result.n == TASKS - 14
    assert evidence.run_health.failed == 14
    assert len(request.eval_result.per_task) == TASKS - 14
    assert set(request.eval_result.per_task).isdisjoint(set(_failed_ids(14)))
    assert "run_health" in evidence.metadata


def test_a_run_above_the_threshold_fails_its_gate():
    evidence = _evidence(failed_tasks=_failed_ids(14))

    assert evidence.eval_result.passed is False
    assert "run health" in evidence.eval_result.detail
    assert "14 of 40" in evidence.eval_result.detail


def test_no_health_data_keeps_todays_bundle():
    evidence = _raw(14)
    blob = json.dumps(evidence.to_dict(), sort_keys=True,
                      separators=(",", ":"), default=str)

    assert "run_health" not in evidence.metadata
    assert "run_health" not in evidence.to_dict()
    assert hashlib.sha256(blob.encode()).hexdigest() == DEFAULT_BUNDLE_SHA256
    assert evidence.eval_result.delta == pytest.approx(0.325)


def test_an_unchanged_artifact_reports_no_gain_even_with_health():
    evidence = replace(_evidence(failed_tasks=_failed_ids(14)),
                       artifact_changed=False)

    assert evidence.eval_result.delta == 0.0
    assert evidence.eval_result.passed is False
    assert evidence.eval_result.detail.count("run health") == 1
    assert evidence.eval_result.detail.count("artifact unchanged") == 1

    rebuilt = replace(evidence)
    assert rebuilt.eval_result.detail.count("artifact unchanged") == 1


def test_an_empty_detail_keeps_one_artifact_note_and_one_hash():
    raw = _raw()
    empty = replace(raw, eval_result=replace(raw.eval_result, detail=""))
    built = replace(empty, artifact_changed=False)
    rebuilt = replace(replace(built, artifact_changed=False),
                      artifact_changed=False)

    assert built.eval_result.detail.count("artifact unchanged") == 1
    assert rebuilt.eval_result.detail.count("artifact unchanged") == 1
    assert rebuilt.eval_result.detail == built.eval_result.detail
    assert (promote(built.to_promotion_request("skill-1"),
                    PromotionRules()).evidence_hash
            == promote(rebuilt.to_promotion_request("skill-1"),
                       PromotionRules()).evidence_hash)


def test_an_empty_detail_with_health_keeps_one_copy_of_each_note():
    raw = _raw(14)
    empty = replace(raw, eval_result=replace(raw.eval_result, detail=""))
    built = replace(empty, artifact_changed=False, metadata={
        "run_health": {"attempted": TASKS,
                       "failed_tasks": _failed_ids(14)}})
    rebuilt = replace(built, artifact_changed=False)

    for evidence in (built, rebuilt):
        detail = evidence.eval_result.detail
        assert detail.count("artifact unchanged") == 1
        assert detail.count("run health") == 1
        assert not detail.startswith("; ")
        assert evidence.eval_result.delta == 0.0
        assert evidence.eval_result.passed is False
    assert rebuilt.eval_result.detail == built.eval_result.detail


def test_a_health_count_without_its_ids_is_a_caller_error():
    with pytest.raises(ValueError):
        replace(_raw(14), metadata={"run_health": {"attempted": TASKS,
                                                  "failed": 14}})
    with pytest.raises(ValueError):
        replace(_raw(14), metadata={"run_health": {"attempted": TASKS,
                                                  "failed": 14,
                                                  "failed_tasks": []}})
    with pytest.raises(ValueError):
        replace(_raw(14), metadata={"run_health": {"attempted": TASKS,
                                                  "failure_rate": 0.35}})


def test_a_health_record_from_to_dict_round_trips():
    evidence = _evidence(failed_tasks=_failed_ids(14))
    rebuilt = replace(_raw(14), metadata={
        "run_health": evidence.run_health.to_dict()})

    assert rebuilt.run_health == evidence.run_health
    assert rebuilt.eval_result.passed is False


def test_a_failure_rate_at_the_threshold_is_not_censored():
    evidence = _evidence(failed_tasks=_failed_ids(8))

    assert evidence.run_health.failure_rate == 0.2
    assert evidence.run_health.censored is False
    assert evidence.eval_result.passed is True


def test_malformed_run_health_is_a_caller_error():
    with pytest.raises(ValueError):
        _decision(failed_tasks=_failed_ids(14), attempted=2)
    with pytest.raises(ValueError):
        _decision(threshold=1.5)
    with pytest.raises(ValueError):
        replace(_raw(2), metadata={"run_health": {"attempted": TASKS,
                                                  "failures": 2}})
