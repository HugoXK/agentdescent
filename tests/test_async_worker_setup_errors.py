"""Failures outside the rollout body must not disappear with a worker thread."""

import importlib
import threading
import warnings

import pytest

from agentdescent.async_evolve import async_evolve
from agentdescent.evolution import SingleSlot, Task
from agentdescent.evolvable import ContractError


TASKS = [Task(id=str(i), prompt=str(i)) for i in range(8)]


def _run(**kwargs):
    return async_evolve(
        TASKS, lambda task, output: 0.0,
        run=lambda rendered, task: "wrong", propose=lambda *args: None,
        strategy=SingleSlot(initial_value="seed"), n_workers=2,
        held_out_frac=0.5, **kwargs)


class _BrokenSampler:
    def pick(self, keys, index):
        raise ValueError("fixture sampler unavailable")

    def record(self, *args):
        pass


@pytest.mark.parametrize("stage", ["initialization", "sampler", "prepare", "observe"])
def test_worker_setup_errors_retire_workers_and_end_the_run(stage, monkeypatch):
    escaped = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args.exc_value))
    kwargs = {}
    message = "fixture " + stage + " unavailable"

    def broken(*args):
        raise ValueError(message)

    if stage == "initialization":
        module = importlib.import_module("agentdescent.async_evolve")
        monkeypatch.setattr(module, "_head_for_worker", broken)
    elif stage == "sampler":
        kwargs["task_sampler"] = _BrokenSampler()
    else:
        class Estimator:
            def estimate(self, cost):
                return 0.0

            def observe(self, cost, elapsed):
                pass

        estimator = Estimator()
        setattr(estimator, "estimate" if stage == "prepare" else "observe", broken)
        kwargs["duration_estimator"] = estimator

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = _run(max_seconds=3.0, **kwargs)

    assert result.error == "ValueError: " + message
    assert result.stop_reason == "error"
    assert result.retired_workers == 2
    assert not escaped
    if stage != "observe":
        assert result.rollouts == 0


def test_setup_contract_error_reaches_the_calling_thread(monkeypatch):
    class BadSampler(_BrokenSampler):
        def pick(self, keys, index):
            raise ContractError("sampler contract violated")

    escaped = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args.exc_value))
    with pytest.raises(ContractError, match="sampler contract violated"):
        _run(max_seconds=1.0, task_sampler=BadSampler())
    assert not escaped


def test_one_setup_failure_keeps_the_other_worker_running(monkeypatch):
    module = importlib.import_module("agentdescent.async_evolve")
    original = module._head_for_worker

    def head(aggregator, wid):
        if wid == 0:
            raise ValueError("worker zero cannot initialize")
        return original(aggregator, wid)

    monkeypatch.setattr(module, "_head_for_worker", head)
    escaped = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args.exc_value))
    result = _run(max_seconds=3.0, max_iters=3)
    assert result.error is None
    assert result.stop_reason == "max_iters"
    assert result.retired_workers == 1
    assert result.rollouts >= 3
    assert not escaped
