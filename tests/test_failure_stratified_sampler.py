"""Failure-stratified sampling: coverage, disjoint splits and transfer (#946).

A search set dominated by one failure mode teaches the proposer that mode, and
the gain vanishes on held-out tasks. These tests pin the two properties that
make the sampler useful: every stratum is sampled, and the search / select /
final sets cannot leak into one another.
"""

import pytest

from agentdescent.evolution import Task, evolve
from agentdescent.sampling import (
    DifficultyWeighted,
    FailureStratifiedSampler,
    RoundRobin,
    TaskSampler,
    TaskSplit,
)


def _three_strata():
    labels = {}
    for i in range(10):
        labels[f"timeout-{i}"] = "timeout"
        labels[f"format-{i}"] = "format"
        labels[f"logic-{i}"] = "logic"
    return labels


def test_failure_stratified_sampler_satisfies_the_protocol():
    assert isinstance(FailureStratifiedSampler(), TaskSampler)


def test_existing_samplers_are_untouched():
    assert isinstance(RoundRobin(), TaskSampler)
    assert isinstance(DifficultyWeighted(), TaskSampler)
    assert RoundRobin().pick(["a", "b"], 3) == "b"


def test_three_strata_are_all_covered_and_none_is_starved():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels, min_per_stratum=2)
    sampler.split(ids)
    for i in range(30):
        sampler.pick(ids, i)

    report = sampler.report()
    assert set(report.coverage) == {"timeout", "format", "logic"}
    assert report.starved == ()
    assert report.ignored == ()
    for coverage in report.coverage.values():
        assert coverage.search > 0
        assert coverage.picks >= 2, coverage


def test_split_is_three_way_disjoint_by_construction():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(ids)

    assert split.is_disjoint()
    assert split.overlap() == {}
    assert set(split.all_ids()) == set(ids)
    assert len(split.all_ids()) == len(ids)
    assert not (set(split.search) & set(split.select))
    assert not (set(split.search) & set(split.final))
    assert not (set(split.select) & set(split.final))
    assert sampler.report().overlap == {}


def test_pick_never_returns_a_hidden_task():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(ids)
    hidden = set(split.select) | set(split.final)

    for i in range(40):
        picked = sampler.pick(ids, i)
        assert picked in split.search
        assert picked not in hidden

    with pytest.raises(ValueError, match="no search task"):
        sampler.pick(list(hidden), 0)


def test_a_leak_is_detected_and_fails_the_split():
    """Disjointness is enforced on assignment; the report still proves it."""
    leaky = TaskSplit(search=("a", "b"), select=("b",), final=("c",))
    assert not leaky.is_disjoint()
    assert leaky.overlap() == {"b": ("search", "select")}


def test_a_dominant_stratum_gets_a_coverage_warning():
    labels = {f"timeout-{i}": "timeout" for i in range(18)}
    labels.update({"format-0": "format", "logic-0": "logic"})
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    sampler.split(ids)
    for i in range(12):
        sampler.pick(ids, i)

    report = sampler.report()
    assert "timeout" in report.dominant
    assert any("dominant" in warning and "timeout" in warning
               for warning in report.warnings)


def test_a_stratum_the_run_never_samples_is_flagged():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    sampler.split(ids)
    timeout_ids = [task_id for task_id, label in labels.items()
                   if label == "timeout"]
    for i in range(6):
        sampler.pick(timeout_ids, i)

    report = sampler.report()
    assert set(report.ignored) == {"format", "logic"}
    assert any("ignored" in warning for warning in report.warnings)


def test_transfer_status_sees_a_selection_gain_that_does_not_hold():
    labels = _three_strata()
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(list(labels))
    for task_id in split.select:
        sampler.record(task_id, 0.9)
    for task_id in split.final:
        sampler.record(task_id, 0.4)

    transfer = sampler.report().transfer
    assert transfer.status == "degrades"
    assert transfer.select_n == len(split.select)
    assert transfer.final_n == len(split.final)
    assert transfer.gap == pytest.approx(0.5)
    assert any("does not transfer" in warning
               for warning in sampler.report().warnings)


def test_transfer_status_holds_when_the_final_set_agrees():
    labels = _three_strata()
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(list(labels))
    for task_id in split.select:
        sampler.record(task_id, 0.8)
    for task_id in split.final:
        sampler.record(task_id, 0.8)

    transfer = sampler.report().transfer
    assert transfer.status == "holds"
    assert transfer.gap == pytest.approx(0.0)


def test_a_callable_signature_and_seed_are_deterministic():
    ids = [f"timeout-{i}" for i in range(4)]
    ids += [f"format-{i}" for i in range(4)]
    ids += [f"logic-{i}" for i in range(4)]

    def signature(task_id):
        return task_id.split("-")[0]

    first = FailureStratifiedSampler(signature, tasks=ids, seed=7)
    second = FailureStratifiedSampler(signature, tasks=ids, seed=7)
    assert first.split(ids) == second.split(ids)
    assert set(first.report().coverage) == {"timeout", "format", "logic"}


def test_a_task_never_moves_split_when_new_ids_arrive():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    before = sampler.split(ids)
    after = sampler.split(ids + ["late-0"])
    # Every pre-existing id keeps its split; checking all three covers a move in
    # either direction (search -> select and select -> search alike).
    assert set(before.search) <= set(after.search)
    assert set(before.select) <= set(after.select)
    assert set(before.final) <= set(after.final)


def test_min_per_stratum_is_configurable():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels, min_per_stratum=3)
    sampler.split(ids)
    for i in range(9):
        sampler.pick(ids, i)
    assert all(coverage.picks >= 3
               for coverage in sampler.report().coverage.values())


def _small_universe(per_stratum=4):
    """12 tasks in three strata: 6 search, 3 select, 3 final."""
    labels = {}
    for stratum in ("timeout", "format", "logic"):
        for i in range(per_stratum):
            labels[f"{stratum}-{i}"] = stratum
    return labels


def test_transfer_status_ignores_float_noise_at_zero_tolerance():
    # 0.1 + 0.2 + 0.3 sums to ...004 in one order and ...000 in another, so the
    # two means of identical scores differ by ~5e-17. A strict gap > 0 flips the
    # status to "improves" on that noise and the status stops meaning anything.
    labels = _small_universe()
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(list(labels))
    assert (len(split.select), len(split.final)) == (3, 3)
    for task_id, score in zip(split.select, (0.1, 0.2, 0.3)):
        sampler.record(task_id, score)
    # Python 3.12+ compensates float summation, so the old 0.3/0.2/0.1 reversal
    # collapses to a 0.0 gap and stops exercising the floor. A 1e-13 difference
    # in one score keeps a deterministic ~3e-14 gap on every supported Python.
    for task_id, score in zip(split.final, (0.1, 0.2, 0.3 - 1e-13)):
        sampler.record(task_id, score)

    transfer = sampler.report().transfer
    assert 0.0 < transfer.gap < 1e-12, "the fixture must carry a sub-floor gap"
    assert transfer.status == "holds"


def test_pick_on_a_shard_without_search_tasks_says_how_to_fix_it():
    labels = _small_universe()
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(list(labels))
    with pytest.raises(ValueError) as err:
        sampler.pick(list(split.select) + list(split.final), 0)
    assert "split()['search']" in str(err.value)


def test_evolve_runs_when_the_task_list_is_the_search_split():
    labels = _small_universe()
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(list(labels))
    tasks = [Task(id=task_id, prompt="p") for task_id in split.search]
    rolled = []

    def run(rendered, task):
        rolled.append(task.id)
        return "answer"

    evolve(tasks, lambda task, output: 0.0, run=run,
           propose=lambda *args: None, task_sampler=sampler,
           n_workers=3, max_concurrency=3, max_rollouts=6, rounds=2, seed=1)

    assert rolled, "the run must roll something out"
    assert set(rolled) <= set(split.search)


def test_a_single_stratum_is_not_reported_as_dominant():
    ids = [f"t{i}" for i in range(6)]
    sampler = FailureStratifiedSampler()
    sampler.split(ids)
    for i in range(3):
        sampler.pick(ids, i)
    report = sampler.report()
    assert report.dominant == ()
    assert not any("dominant" in warning for warning in report.warnings)
