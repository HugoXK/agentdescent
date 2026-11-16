"""The two ports #924 asks for, and a file-backed reference for each.

An artifact is a tree of files with revisions: a worker proposes bytes, the
store keeps every revision, and ``promote`` names the one an evaluation reads.
#924 makes that a port instead of a convention, so a directory or object store
can back it without the loop copying files around -- and splits the evaluation
side the same way: :class:`EvaluationProvider` supplies a split, the scorer a run
optimises, the two references a caller can check it against, and the
contamination screen.

``FileArtifactStore`` keeps ``<root>/<artifact_id>/<revision>/`` plus
``<revision>.json`` (parent, message); a name or path that could leave ``root``
raises ``ValueError`` before a write. A symlink planted at a leaf it writes is
refused the same way, and a hardlink at a leaf is replaced rather than written
through; a symlinked *directory* above a leaf stays legal (a store on another
disk is a configuration, not an escape). ``CsvEvaluationProvider`` keeps one
``<root>/<split>.csv`` per split and reuses ``rewards.exact_match`` and
``stats_eval.contamination_overlap`` rather than re-deriving either. Stdlib only
at import: the evolve stack is imported inside the methods that need it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Dict, Mapping, Optional, Protocol, Sequence, Tuple, Union,
    runtime_checkable,
)

if TYPE_CHECKING:  # runtime-free: `ports` stays stdlib-only at import
    from .evolution import Task

_SAFE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@dataclass(frozen=True)
class Diff:
    """Added / removed / changed paths; sorted, so two runs print identically."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()


@runtime_checkable
class ArtifactStore(Protocol):
    """``read_tree``/``write_tree`` speak bytes (a weight is not UTF-8);
    ``list_revisions`` is sorted; ``promote`` copies a revision to a name and is
    idempotent."""

    def read_tree(self, artifact_id: str, revision: str) -> Dict[str, bytes]: ...

    def write_tree(self, artifact_id: str, files: Mapping[str, bytes], *,
                   parent: Optional[str] = None, message: str = "") -> str: ...

    def list_revisions(self, artifact_id: str) -> Sequence[str]: ...

    def diff(self, artifact_id: str, base: str, target: str) -> Diff: ...

    def promote(self, artifact_id: str, revision: str, *, to: str) -> None: ...


def _name(value: str, what: str) -> str:
    if not isinstance(value, str) or not _SAFE_NAME.match(value):
        raise ValueError(f"unsafe {what} {value!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
    return value


def _relpath(path: str) -> str:
    if not path or not isinstance(path, str) or path.startswith("/") or "\x00" in path:
        raise ValueError(f"unsafe file path {path!r}: expected a relative path")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"unsafe file path {path!r}: expected a relative path")
    return path


def _write_sidecar(path: Path, parent: Optional[str], message: str) -> None:
    """Write the revision sidecar by rename, never through the leaf (#1041).

    ``write_text`` truncated the inode of a hardlink planted at
    ``<revision>.json``, whose bytes live outside ``root``; it also left a
    check-then-use window between the leaf guard and the write. A staged file
    renamed over the leaf replaces the directory entry instead, so the bytes
    behind any link survive and no link is followed.
    """
    payload = json.dumps({"parent": parent, "message": message}, sort_keys=True) + "\n"
    handle, staged = tempfile.mkstemp(
        prefix=".staging-", suffix=".json", dir=str(path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(staged, path)
    except BaseException:
        try:
            os.unlink(staged)
        except OSError:
            pass
        raise


def _refuse_linked_leaf(path: Path) -> None:
    """Refuse a link planted at ``path`` itself (#1041).

    ``Path.write_text`` follows a link at the leaf, and ``shutil.rmtree``
    refuses one with a raw ``OSError``: either way the documented ``ValueError``
    was not what a caller got, and the sidecar write landed outside ``root``.
    The rule is ``filetree.leaf_problem``: only the leaf is tested, so a
    symlinked *directory* above the store stays legal. A hardlink is not
    refused here -- it shares the inode, so :func:`_write_sidecar` replaces the
    entry instead of writing through it.
    """
    from .filetree import leaf_problem

    problem = leaf_problem(str(path))
    if problem is not None:
        raise ValueError(f"cannot write {path}: {problem}")


def _revision_name(parent: Optional[str], files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256(b"agentdescent.ports.v1\0")
    digest.update((parent or "").encode("utf-8") + b"\0")
    for path in sorted(files):
        data = files[path]
        digest.update(path.encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return "r-" + digest.hexdigest()[:16]


class FileArtifactStore:
    """The reference backend: a directory tree under ``root``; every revision is
    staged and renamed, so a partial one is never listed."""

    def __init__(self, root: Union[str, os.PathLike]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def read_tree(self, artifact_id: str, revision: str) -> Dict[str, bytes]:
        return self._read(self._dir(artifact_id, revision))

    def write_tree(self, artifact_id: str, files: Mapping[str, bytes], *,
                   parent: Optional[str] = None, message: str = "") -> str:
        artifact = self._dir(artifact_id)
        if parent is not None:
            _name(parent, "parent revision")
        for path in files:
            _relpath(path)
        payload = {path: bytes(data) for path, data in dict(files).items()}
        revision = _revision_name(parent, payload)
        # Before is_dir(): both branches below follow a link planted here, so a
        # dangling one reached the rename as a raw NotADirectoryError and one to
        # a directory outside the store skipped the write and served the outside
        # tree as this revision (#1050).
        _refuse_linked_leaf(artifact / revision)
        if not (artifact / revision).is_dir():
            self._commit(artifact, revision, payload, parent, message)
        return revision

    def list_revisions(self, artifact_id: str) -> Sequence[str]:
        artifact = self._dir(artifact_id)
        if not artifact.is_dir():
            return ()
        return tuple(sorted(
            entry.name for entry in artifact.iterdir()
            if entry.is_dir() and _SAFE_NAME.match(entry.name)
        ))

    def diff(self, artifact_id: str, base: str, target: str) -> Diff:
        before = self.read_tree(artifact_id, base)
        after = self.read_tree(artifact_id, target)
        changed = [p for p in set(before) & set(after) if before[p] != after[p]]
        return Diff(
            added=tuple(sorted(set(after) - set(before))),
            removed=tuple(sorted(set(before) - set(after))),
            changed=tuple(sorted(changed)),
        )

    def promote(self, artifact_id: str, revision: str, *, to: str) -> None:
        artifact = self._dir(artifact_id)
        files = self._read(self._dir(artifact_id, revision))
        target = artifact / _name(to, "promotion target")
        # Before is_dir/read/rmtree: a link here would be followed into the
        # outside tree and then refused by rmtree as a raw OSError (#1041).
        _refuse_linked_leaf(target)
        if target.is_dir():
            if self._read(target) == files:
                return
            shutil.rmtree(target)
        self._commit(artifact, target.name, files, None, "")

    def _dir(self, artifact_id: str, revision: Optional[str] = None) -> Path:
        directory = self.root / _name(artifact_id, "artifact id")
        if revision is None:
            return directory
        directory = directory / _name(revision, "revision")
        if not directory.is_dir():
            raise FileNotFoundError(f"no revision {revision!r} for artifact {artifact_id!r}")
        return directory

    def _commit(self, artifact: Path, name: str, files: Mapping[str, bytes],
                parent: Optional[str], message: str) -> None:
        target = artifact / name
        # Before mkdir and staging: a regular file at the tree's leaf reached
        # os.replace as a raw NotADirectoryError (#1045).
        if target.exists() and not target.is_dir():
            raise ValueError(f"cannot write {target}: not a directory")
        sidecar = artifact / (name + ".json")
        # Before mkdir and staging: a symlink here would be followed into the
        # outside tree, and the sidecar would land outside the store (#1041).
        # The revision leaf is guarded too, so a caller that skipped the check in
        # ``write_tree`` (or a future one) cannot reach the rename either (#1050).
        _refuse_linked_leaf(artifact / name)
        _refuse_linked_leaf(sidecar)
        # A directory here reached the sidecar rename as a raw IsADirectoryError
        # only after the tree had landed, so the revision was listed without a
        # sidecar (#1045).
        if sidecar.exists() and not sidecar.is_file():
            raise ValueError(f"cannot write {sidecar}: not a file")
        artifact.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(artifact)))
        try:
            for path, data in files.items():
                destination = staging / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            os.replace(staging, artifact / name)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        _write_sidecar(sidecar, parent, message)

    @staticmethod
    def _read(directory: Path) -> Dict[str, bytes]:
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }


# ---------------------------------------------------------------------------
# The evaluation port (#924)
# ---------------------------------------------------------------------------


@runtime_checkable
class EvaluationProvider(Protocol):
    """Where a run's tasks and scores come from: five methods, no file layout.

    ``tasks`` supplies a split as :class:`agentdescent.evolution.Task`;
    ``reward`` is the number a run optimises, ``(task, output) -> float``, the
    same shape ``evolve(tasks, reward)`` already takes; ``oracle`` and ``judge``
    are the two independent references a caller can compare that number
    against -- a gold-answer scorer and a model-based one -- and both return
    ``None`` rather than invent a value, because "this split has no labels" and
    "no judge is configured" are not score 0. ``contamination`` reports how much
    of the split also appears in the others, in whatever shape the backend can
    honestly fill.

    ``@runtime_checkable`` is the conformance check: ``isinstance(backend,
    EvaluationProvider)`` proves a candidate has the five methods without the
    backend importing this module, which is the point of a port.
    """

    def tasks(self, split: str) -> Sequence["Task"]: ...

    def reward(self, task: "Task", output: str) -> float: ...

    def oracle(self, task: "Task", output: str) -> Optional[float]: ...

    def judge(self, task: "Task", output: str) -> Optional[float]: ...

    def contamination(self, tasks: Sequence["Task"]) -> Mapping[str, Any]: ...


class CsvEvaluationProvider:
    """The reference backend: one ``<root>/<split>.csv`` per split, first row a
    header, a ``prompt`` column and a ``gold`` column.

    ``reward`` is ``rewards.exact_match`` on ``gold_column`` unless ``scorer=``
    replaces it -- the existing scorers are the contract, so a port that scores
    differently says so rather than re-deriving one. Every task carries the label
    under ``meta[gold_column]`` (plus ``meta["split"]``), which is where the
    built-in scorers and the reflector already look.

    What this backend cannot do is reported as ``None``, never as a number:
    ``oracle`` returns ``None`` on a row with no label, and ``judge`` returns
    ``None`` until a ``judge=`` callable is injected. A caller reading a 0.0
    there would conclude the model failed instead of the dataset being
    unlabelled, which is the silent failure ``rewards.last_number`` documents.
    ``reward`` on an unlabelled row raises the scorer's ``KeyError`` for the same
    reason.

    ``contamination`` reuses ``stats_eval.contamination_overlap`` against every
    other split in the directory, so ``overlap`` keeps that function's meaning --
    and its ``None`` for "there were no n-grams to screen".
    """

    def __init__(self, root: Union[str, os.PathLike], *, prompt_column: str = "prompt",
                 gold_column: str = "gold", scorer: Optional[Any] = None,
                 judge: Optional[Any] = None) -> None:
        self.root = Path(root)
        self.prompt_column = prompt_column
        self.gold_column = gold_column
        self._scorer = scorer
        self._judge = judge
        self._loaded: Dict[str, Tuple["Task", ...]] = {}

    def tasks(self, split: str) -> Sequence["Task"]:
        """The rows of ``<root>/<split>.csv``, cached: a run asks once per round."""
        if split not in self._loaded:
            self._loaded[split] = self._load(split)
        return self._loaded[split]

    def splits(self) -> Tuple[str, ...]:
        """The split names present in the directory, sorted."""
        if not self.root.is_dir():
            return ()
        return tuple(sorted(
            entry.stem for entry in self.root.glob("*.csv")
            if entry.is_file() and _SAFE_NAME.match(entry.stem)
        ))

    def reward(self, task: "Task", output: str) -> float:
        return float(self._scorer_callable()(task, output))

    def oracle(self, task: "Task", output: str) -> Optional[float]:
        if self.gold_column not in (getattr(task, "meta", None) or {}):
            return None
        return float(self.reward(task, output))

    def judge(self, task: "Task", output: str) -> Optional[float]:
        if self._judge is None:
            return None
        score = self._judge(task, output)
        return None if score is None else float(score)

    def contamination(self, tasks: Sequence["Task"]) -> Mapping[str, Any]:
        from .stats_eval import contamination_overlap

        tasks = list(tasks)
        own = {str(task.meta.get("split")) for task in tasks if getattr(task, "meta", None)}
        against = tuple(split for split in self.splits() if split not in own)
        prompts = [task.prompt for task in tasks]
        overlap: Dict[str, Optional[float]] = {
            split: contamination_overlap([task.prompt for task in self.tasks(split)],
                                         prompts).overlap
            for split in against
        }
        screened = [value for value in overlap.values() if value is not None]
        return {
            "tasks": len(tasks),
            "against": against,
            "overlap": overlap,
            # None when nothing could be screened -- "we could not look" is not
            # "clean" (stats_eval.ContaminationReport says the same).
            "max_overlap": max(screened) if screened else None,
        }

    def _scorer_callable(self) -> Any:
        if self._scorer is None:
            from .rewards import exact_match

            self._scorer = exact_match(self.gold_column)
        return self._scorer

    def _load(self, split: str) -> Tuple["Task", ...]:
        from .evolution import Task

        path = self.root / (_name(split, "split") + ".csv")
        if not path.is_file():
            raise FileNotFoundError(f"no split {split!r}: {path} is not a file")
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if rows and self.prompt_column not in rows[0]:
            raise ValueError(
                f"{path}: no {self.prompt_column!r} column; the file has "
                f"{sorted(rows[0])}")
        loaded = []
        for index, row in enumerate(rows):
            meta: Dict[str, Any] = {"split": split}
            if self.gold_column in row:
                meta[self.gold_column] = row[self.gold_column]
            identifier = row.get("id") or f"{split}-{index}"
            loaded.append(Task(id=str(identifier),
                               prompt=row[self.prompt_column] or "", meta=meta))
        return tuple(loaded)
