"""`ExperienceStore.add` refuses a link at the store leaf before appending (#1064).

The store opens the user-named `--store` path in append mode, so a link planted
at that leaf grows the bytes behind it: a symlink writes into the outside file,
a hardlink writes into the shared inode, and a dangling symlink creates the
file at the link's target. The write is refused before the first byte, with the
same `cannot write <path>: <problem>` shape the sibling writers use, and the
operator's link and the outside bytes are left alone.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentdescent.experience import ExperienceRecord, ExperienceStore

OUTSIDE = b"ORIGINAL-OUTSIDE-BYTES\n"


def _record(run_id: str = "run-1") -> ExperienceRecord:
    return ExperienceRecord(run_id, (1.0,), {"a": 1.0, "b": 0.0},
                            artifact_id=f"artifact-{run_id}")


def _store(tmp_path: Path) -> tuple[ExperienceStore, Path]:
    path = tmp_path / "experience.jsonl"
    return ExperienceStore(str(path)), path


def test_a_symlink_at_the_store_leaf_is_refused(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(OUTSIDE)
    path.symlink_to(outside)

    with pytest.raises(ValueError, match=r"cannot write .*experience\.jsonl: .*is a symlink"):
        store.add(_record())

    assert outside.read_bytes() == OUTSIDE
    assert path.is_symlink()
    assert store._rows == []


def test_a_hardlink_at_the_store_leaf_is_refused(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(OUTSIDE)
    os.link(outside, path)

    with pytest.raises(ValueError, match=r"cannot write .*experience\.jsonl: .*links"):
        store.add(_record())

    assert outside.read_bytes() == OUTSIDE
    assert path.stat().st_nlink == 2
    assert store._rows == []


def test_a_dangling_symlink_at_the_store_leaf_is_refused(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    gone = tmp_path / "gone.jsonl"
    path.symlink_to(gone)

    with pytest.raises(ValueError, match=r"cannot write .*experience\.jsonl: .*is a symlink"):
        store.add(_record())

    assert not gone.exists()
    assert path.is_symlink()


def test_a_directory_at_the_store_leaf_is_refused(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    store.add(_record("first"))
    path.unlink()
    path.mkdir()

    with pytest.raises(ValueError, match=r"cannot write .*experience\.jsonl: not a regular file"):
        store.add(_record("second"))

    assert path.is_dir()
    assert [row.run_id for row in store._rows] == ["first"]


def test_a_plain_store_still_appends_and_reloads(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    store.add(_record("first"))
    store.add(_record("second"))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [line.count('"run_id"') for line in lines] == [1, 1]
    reloaded = ExperienceStore(str(path))
    assert [row.run_id for row in reloaded._rows] == ["first", "second"]
