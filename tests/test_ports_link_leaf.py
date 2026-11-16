"""`FileArtifactStore.write_tree` refuses a link at the derived revision leaf (#1050).

`write_tree` decided "already there?" with `is_dir()` and `_commit` decided with
`exists()`, and both follow a symlink, so nothing stood between a link planted at
`<root>/<artifact>/r-<hash>` and the write:

* a dangling link made `target.exists()` false, so the `#1045` guard did not
  fire and `os.replace` raised a raw `NotADirectoryError`;
* a link to a directory outside the store made `is_dir()` true, so the write was
  skipped and the outside tree was served as a revision of the artifact.

Both are refused before the first byte now, and the operator's link survives.
The read side is deliberately not pinned here: as specified in #1050 the planted
name still resolves on `read_tree`/`list_revisions`, and a read-side guard is a
separate card.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentdescent.ports import FileArtifactStore

OUTSIDE = b"ORIGINAL-OUTSIDE-BYTES\n"


def _derived(scratch: Path, files: dict[str, bytes]) -> str:
    """The revision name `write_tree` derives; the name depends on content only."""
    return FileArtifactStore(scratch).write_tree("img", files)


def _staging(artifact: Path) -> list[Path]:
    return sorted(artifact.glob(".staging-*"))


class TestALinkAtTheDerivedRevisionLeafIsRefused:
    def test_a_dangling_link_is_refused_before_the_rename(self, tmp_path: Path) -> None:
        store = FileArtifactStore(tmp_path / "store")
        revision = _derived(tmp_path / "scratch", {"a.txt": b"A\n"})
        artifact = tmp_path / "store" / "img"
        artifact.mkdir(parents=True)
        link = artifact / revision
        link.symlink_to(tmp_path / "nowhere")

        with pytest.raises(
            ValueError, match=r"cannot write .*r-[0-9a-f]{16}: .*is a symlink",
        ):
            store.write_tree("img", {"a.txt": b"A\n"})

        assert link.is_symlink()
        assert not link.exists()
        assert _staging(artifact) == []
        assert store.list_revisions("img") == ()

    def test_a_link_to_an_outside_directory_is_refused_before_any_byte(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "leak.txt").write_bytes(OUTSIDE)
        store = FileArtifactStore(tmp_path / "store")
        revision = _derived(tmp_path / "scratch", {"a.txt": b"A\n"})
        artifact = tmp_path / "store" / "img"
        artifact.mkdir(parents=True)
        link = artifact / revision
        link.symlink_to(outside, target_is_directory=True)

        with pytest.raises(
            ValueError, match=r"cannot write .*r-[0-9a-f]{16}: .*is a symlink",
        ):
            store.write_tree("img", {"a.txt": b"A\n"})

        assert link.is_symlink()
        assert (outside / "leak.txt").read_bytes() == OUTSIDE
        assert not (outside / "a.txt").exists()
        assert _staging(artifact) == []


class TestTheGuardLeavesOrdinaryWritesAlone:
    def test_a_fresh_artifact_and_a_parented_write_both_land(self, tmp_path: Path) -> None:
        store = FileArtifactStore(tmp_path / "store")

        first = store.write_tree("img", {"a.txt": b"A\n"})
        second = store.write_tree("img", {"a.txt": b"B\n"}, parent=first, message="second")

        assert store.list_revisions("img") == tuple(sorted((first, second)))
        assert store.read_tree("img", first) == {"a.txt": b"A\n"}
        assert store.read_tree("img", second) == {"a.txt": b"B\n"}
        assert _staging(tmp_path / "store" / "img") == []

    def test_a_symlinked_artifact_directory_above_the_leaves_still_writes(self, tmp_path: Path) -> None:
        real = tmp_path / "real-store"
        real.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(real, target_is_directory=True)
        store = FileArtifactStore(alias)

        revision = store.write_tree("img", {"a.txt": b"A\n"})

        assert store.read_tree("img", revision) == {"a.txt": b"A\n"}
        assert (real / "img" / f"{revision}.json").is_file()
