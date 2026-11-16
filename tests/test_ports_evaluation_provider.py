"""`ports.EvaluationProvider` and the `CsvEvaluationProvider` reference (#924).

Pins the conformance check, the CSV round trip and its refusals, the honest
``None`` from ``oracle``/``judge``, contamination against the other splits, and
the #924 acceptance line: the same run through the provider and through a
hand-rolled CSV reader reports the same baseline and final scores.
"""

from __future__ import annotations

import ast
import csv
from pathlib import Path

import pytest

import agentdescent.ports as ports_module
from agentdescent.evolution import evolve
from agentdescent.ports import CsvEvaluationProvider, EvaluationProvider
from agentdescent.rewards import exact_match

#: Long enough that `contamination_overlap`'s five-gram screen sees grams; the
#: numbers differ so the gold answers do too.
ROWS = [
    {"id": f"t{index}",
     "prompt": f"A basket holds {index} apples. Ann adds 2 more apples to the basket. "
               f"How many apples are in the basket now?",
     "gold": str(index + 2)}
    for index in range(12)
]

COLUMNS = ("id", "prompt", "gold")


def write_split(root: Path, split: str, rows=ROWS, *, columns=COLUMNS) -> Path:
    """Write one ``<split>.csv`` the way a dataset ships: a header, then rows."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{split}.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
    return path


def read_split_directly(path: Path) -> list:
    """The file-based baseline the acceptance row compares against."""
    from agentdescent.evolution import Task

    with path.open(newline="", encoding="utf-8") as stream:
        return [
            Task(id=row["id"], prompt=row["prompt"], meta={"gold": row["gold"]})
            for row in csv.DictReader(stream)
        ]


def test_ports_keeps_the_evolve_stack_out_of_its_module_imports() -> None:
    """The port is stdlib-only at import: the package's own imports come inside
    the methods (or under ``TYPE_CHECKING``).

    ``agentdescent/__init__`` imports the loop for every import path, so this
    pins the module itself -- a top-level ``from .evolution import Task`` would
    hide the layering and make a cycle easy to introduce later.
    """
    tree = ast.parse(Path(ports_module.__file__).read_text(encoding="utf-8"))
    top_level = [node for node in tree.body
                 if isinstance(node, ast.ImportFrom) and node.level > 0]
    assert top_level == []


def test_the_reference_backend_satisfies_the_protocol(tmp_path: Path) -> None:
    """`isinstance` is the conformance check the protocol exists for."""
    provider = CsvEvaluationProvider(tmp_path / "data")
    assert isinstance(provider, EvaluationProvider)

    class _ObjectStoreProvider:
        def tasks(self, split):
            return ()

        def reward(self, task, output):
            return 0.0

        def oracle(self, task, output):
            return None

        def judge(self, task, output):
            return None

        def contamination(self, tasks):
            return {}

    # Structural, not nominal: a backend that stores splits in a database is an
    # `EvaluationProvider` without importing this module.
    assert isinstance(_ObjectStoreProvider(), EvaluationProvider)


def test_tasks_read_each_split_and_carry_the_label(tmp_path: Path) -> None:
    root = tmp_path / "data"
    write_split(root, "train", ROWS[:3])
    write_split(root, "val", ROWS[3:5])
    provider = CsvEvaluationProvider(root)

    train = provider.tasks("train")
    assert [task.id for task in train] == ["t0", "t1", "t2"]
    assert train[0].prompt == ROWS[0]["prompt"]
    assert train[0].meta == {"split": "train", "gold": ROWS[0]["gold"]}
    assert [task.id for task in provider.tasks("val")] == ["t3", "t4"]


def test_a_split_that_could_leave_the_root_is_refused(tmp_path: Path) -> None:
    write_split(tmp_path, "outside", ROWS[:1])
    root = tmp_path / "store"
    root.mkdir()
    provider = CsvEvaluationProvider(root)

    for unsafe in ("../outside", "/etc/passwd", "a/b"):
        with pytest.raises(ValueError, match="unsafe split"):
            provider.tasks(unsafe)


def test_a_missing_column_or_split_is_named_not_silently_skipped(tmp_path: Path) -> None:
    root = tmp_path / "data"
    write_split(root, "train", [{"id": "t0", "gold": "4"}], columns=("id", "gold"))
    provider = CsvEvaluationProvider(root)

    with pytest.raises(ValueError, match="no 'prompt' column"):
        provider.tasks("train")
    with pytest.raises(FileNotFoundError, match="no split 'test'"):
        provider.tasks("test")


def test_reward_is_the_existing_scorer_and_a_missing_label_is_never_a_zero(
        tmp_path: Path) -> None:
    root = tmp_path / "data"
    write_split(root, "train", ROWS[:1])
    write_split(root, "test", [{"id": "x", "prompt": ROWS[0]["prompt"]}],
                columns=("id", "prompt"))
    provider = CsvEvaluationProvider(root)

    task = provider.tasks("train")[0]
    gold = ROWS[0]["gold"]
    assert provider.reward(task, gold) == 1.0
    assert provider.reward(task, gold + "0") == 0.0
    assert provider.reward(task, gold) == exact_match()(task, gold)

    unlabelled = provider.tasks("test")[0]
    with pytest.raises(KeyError, match="gold"):
        provider.reward(unlabelled, gold)
    # "no label" is not "scored 0": both references say they could not score it.
    assert provider.oracle(unlabelled, gold) is None
    assert provider.judge(unlabelled, gold) is None
    assert provider.oracle(task, gold) == 1.0
    assert provider.judge(task, gold) is None

    judged = CsvEvaluationProvider(root, judge=lambda task, output: 0.5)
    assert judged.judge(task, "anything") == 0.5


def test_contamination_compares_the_split_with_the_others(tmp_path: Path) -> None:
    root = tmp_path / "data"
    unrelated = [
        "Translate the sentence about a library into French, keeping the tone.",
        "Name the chemical element with the atomic number sixty two, briefly.",
        "Summarise the paragraph about the harbour strike in two sentences.",
        "List three differences between a compiler and an interpreter, plainly.",
    ]
    write_split(root, "train", ROWS[:4])
    write_split(root, "val", ROWS[:4])          # a verbatim copy: a leak
    write_split(root, "test", [
        {"id": f"u{index}", "prompt": prompt, "gold": ""}
        for index, prompt in enumerate(unrelated)
    ])
    provider = CsvEvaluationProvider(root)

    leaked = provider.contamination(provider.tasks("val"))
    assert leaked["against"] == ("test", "train")
    assert leaked["overlap"]["train"] == 1.0
    assert leaked["overlap"]["test"] < 0.2
    assert leaked["max_overlap"] == 1.0

    clean = provider.contamination(provider.tasks("test"))
    assert clean["against"] == ("train", "val")
    assert all(value is not None and value < 0.2 for value in clean["overlap"].values())


def test_contamination_returns_none_when_it_could_not_screen(tmp_path: Path) -> None:
    """Short text has no n-grams: "we could not look" must not read as clean."""
    root = tmp_path / "data"
    write_split(root, "train", ROWS[:2])
    write_split(root, "tiny", [{"id": "s0", "prompt": "yes", "gold": ""}])
    provider = CsvEvaluationProvider(root)

    report = provider.contamination(provider.tasks("tiny"))
    assert report["overlap"]["train"] is None
    assert report["max_overlap"] is None


def test_a_run_scores_the_same_through_the_provider_as_through_a_file(
        tmp_path: Path) -> None:
    """The #924 acceptance line: the adapter changes the plumbing, not the score."""
    root = tmp_path / "data"
    path = write_split(root, "train", ROWS)
    provider = CsvEvaluationProvider(root)

    class _Agent:
        def solve(self, rendered, task):
            return task.meta["gold"] if "answer:" in rendered else "0"

        def propose(self, rendered, task, output, reward):
            return "answer: " + task.meta["gold"] + "\n" + rendered

    through_provider = evolve(provider.tasks("train"), provider.reward,
                              agent=_Agent(), rounds=3)
    direct = evolve(read_split_directly(path), exact_match(), agent=_Agent(), rounds=3)

    assert through_provider.initial_reward == direct.initial_reward
    assert through_provider.final_reward == direct.final_reward
    assert [round.held_out_reward for round in through_provider.history] == \
        [round.held_out_reward for round in direct.history]
