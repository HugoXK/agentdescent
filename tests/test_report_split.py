"""The reported reward is a select set, not an unseen test (#843).

Selection -- which candidate becomes head -- and the number a run reports both
use the same held-out split, so the printed reward is the score of the set that
chose the winner. That is optimistic, and the CLI now says so.

The fix in this slice is optional and additive: ``evolve(..., test_frac=0.5)``
carves a test partition out of the held-out set **after** the select partition,
scores it once at the end, and reports it separately. Selection never sees those
task ids. ``test_frac=0`` (the default) is the old run exactly, except that the
CLI/manifest now states plainly that the reward it prints is select-set.
"""

import pytest

from agentdescent import Task, evolve
from agentdescent.evolution import SELECT_SET_NOTE, reward_set_line


def _tasks(n_easy: int, n_hard: int):
    tasks = []
    for i in range(n_easy):
        tasks.append(Task(f"easy-{i}", f"prompt {i}", {"easy": True}))
    for i in range(n_hard):
        tasks.append(Task(f"hard-{i}", f"prompt {i}", {"easy": False}))
    return tasks


def _reward(task, output):
    """A deliberately overfit scorer: it passes the select partition only."""
    return 1.0 if task.meta.get("easy") else 0.0


def _agent(seen):
    def run(rendered, task):
        seen.append(task.id)
        return "answer"

    def propose(rendered, task, output, reward):
        return None

    return run, propose


@pytest.mark.filterwarnings("ignore::agentdescent.evolution.SmallHeldOutWarning")
def test_a_deliberately_overfit_select_score_diverges_from_the_test_split():
    # 12 tasks, held_out_frac=0.5 -> held-out tasks are easy-0..2, hard-0..2;
    # test_frac=0.5 -> select = the three easy tasks, test = the three hard ones.
    tasks = _tasks(9, 3)
    seen = []
    run, propose = _agent(seen)
    result = evolve(tasks, _reward, run=run, propose=propose, rounds=1,
                    n_workers=1, held_out_frac=0.5, test_frac=0.5,
                    shuffle=False)
    assert result.final_reward == 1.0
    assert result.test_reward == 0.0
    assert result.test_tasks == 3
    assert result.select_tasks == 3


@pytest.mark.filterwarnings("ignore::agentdescent.evolution.SmallHeldOutWarning")
def test_select_never_sees_the_test_task_ids():
    tasks = _tasks(9, 3)
    seen = []
    run, propose = _agent(seen)
    result = evolve(tasks, _reward, run=run, propose=propose, rounds=1,
                    n_workers=1, held_out_frac=0.5, test_frac=0.5,
                    shuffle=False)
    # The three hard tasks are the test partition. They are scored exactly once,
    # at the end; no round, proposal or acceptance gate may have measured them.
    assert all(seen.count(f"hard-{i}") == 1 for i in range(3))
    assert result.test_reward == 0.0


def test_without_a_split_the_old_numbers_are_unchanged():
    tasks = _tasks(9, 3)
    seen = []
    run, propose = _agent(seen)
    result = evolve(tasks, _reward, run=run, propose=propose, rounds=1,
                    n_workers=1, held_out_frac=0.5)
    # 6 held-out tasks: 3 easy (1.0) and 3 hard (0.0).
    assert result.final_reward == 0.5
    assert result.test_reward is None
    assert result.select_tasks == 6
    assert "select set" in SELECT_SET_NOTE
    assert "not an unseen test set" in SELECT_SET_NOTE


def test_the_printed_line_says_which_set_the_reward_is():
    assert "select set" in reward_set_line(0.5)
    assert "test reward" in reward_set_line(0.5, 0.25)
    assert "0.250" in reward_set_line(0.5, 0.25)
