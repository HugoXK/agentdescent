"""`FileArtifactStore` refuses a link planted at a leaf it writes (#1041).

`_commit` wrote `<name>.json` with `Path.write_text`, which follows a link at
that leaf, and `promote` read and `rmtree`d `<to>` before the sidecar was
written -- so at live main a link under the store overwrote bytes outside
`root`; a hardlink shares the inode, so the outside bytes were truncated even
when the store refused to follow anything. Each symlink shape is refused before
the write, a hardlink is replaced rather than written through, the operator's
link survives, the target keeps its bytes, and no staging file is left behind.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentdescent.ports import FileArtifactStore

OUTSIDE = b"ORIGINAL-OUTSIDE-BYTES\n"


def _store(tmp_path: Path) -> tuple[FileArtifactStore, Path, Path]:
    outside = tmp_path / "outside"
    outside.mkdir()
    keep = outside / "keep.json"
    keep.write_bytes(OUTSIDE)
    return FileArtifactStore(tmp_path / "store"), outside, keep


def _staging(artifact: Path) -> list[Path]:
    return sorted(artifact.glob(".staging-*"))


class TestALinkAtAWrittenLeafIsRefused:
    """The six link shapes from #1041: symlinks refused, hardlinks replaced."""

    def test_promote_refuses_a_link_at_the_sidecar(self, tmp_path: Path) -> None:
        store, _, keep = _store(tmp_path)
        revision = store.write_tree("img", {"a.txt": b"A\n"}, parent=None)
        artifact = tmp_path / "store" / "img"
        link = artifact / "prod.json"
        link.symlink_to(keep)

        with pytest.raises(ValueError, match=r"cannot write .*prod\.json: .*is a symlink"):
            store.promote("img", revision, to="prod")

        assert keep.read_bytes() == OUTSIDE
        assert link.is_symlink()
        assert _staging(artifact) == []

    def test_promote_refuses_the_link_before_replacing_a_stale_target(self, tmp_path: Path) -> None:
        store, _, keep = _store(tmp_path)
        revision = store.write_tree("img", {"a.txt": b"A\n"}, parent=None)
        artifact = tmp_path / "store" / "img"
        stale = artifact / "prod"
        stale.mkdir()
        (stale / "old.txt").write_bytes(b"old\n")
        link = artifact / "prod.json"
        link.symlink_to(keep)

        with pytest.raises(ValueError, match=r"cannot write .*prod\.json: .*is a symlink"):
            store.promote("img", revision, to="prod")

        assert keep.read_bytes() == OUTSIDE
        assert link.is_symlink()
        assert _staging(artifact) == []

    def test_promote_refuses_a_link_at_the_target_directory(self, tmp_path: Path) -> None:
        store, outside, keep = _store(tmp_path)
        revision = store.write_tree("img", {"a.txt": b"A\n"}, parent=None)
        artifact = tmp_path / "store" / "img"
        link = artifact / "prod"
        link.symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match=r"cannot write .*prod: .*is a symlink"):
            store.promote("img", revision, to="prod")

        assert keep.read_bytes() == OUTSIDE
        assert not (outside / "a.txt").exists()
        assert link.is_symlink()
        assert _staging(artifact) == []

    def test_write_tree_refuses_a_link_at_its_sidecar(self, tmp_path: Path) -> None:
        store, _, keep = _store(tmp_path)
        # The revision name is derived from the content, so a scratch store
        # gives the same one this call would write.
        revision = FileArtifactStore(tmp_path / "scratch").write_tree("img", {"a.txt": b"A\n"})
        artifact = tmp_path / "store" / "img"
        artifact.mkdir(parents=True)
        link = artifact / f"{revision}.json"
        link.symlink_to(keep)

        with pytest.raises(ValueError, match=r"cannot write .*\.json: .*is a symlink"):
            store.write_tree("img", {"a.txt": b"A\n"})

        assert keep.read_bytes() == OUTSIDE
        assert link.is_symlink()
        assert _staging(artifact) == []
        assert store.list_revisions("img") == ()

    def test_a_plain_store_still_writes_and_promotes(self, tmp_path: Path) -> None:
        store, _, keep = _store(tmp_path)
        revision = store.write_tree("img", {"a.txt": b"A\n"})
        store.promote("img", revision, to="prod")

        assert store.read_tree("img", "prod") == {"a.txt": b"A\n"}
        assert keep.read_bytes() == OUTSIDE
        assert _staging(tmp_path / "store" / "img") == []

    def test_a_symlinked_directory_above_the_leaf_stays_legal(self, tmp_path: Path) -> None:
        real = tmp_path / "real-store"
        real.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(real, target_is_directory=True)
        store = FileArtifactStore(alias)

        revision = store.write_tree("img", {"a.txt": b"A\n"})

        assert store.read_tree("img", revision) == {"a.txt": b"A\n"}
        assert (real / "img" / f"{revision}.json").is_file()

    def test_promote_leaves_a_hardlinked_sidecar_alone(self, tmp_path: Path) -> None:
        """A hardlink shares the inode, so a followed write cannot be undone."""
        store, _, keep = _store(tmp_path)
        revision = store.write_tree("img", {"a.txt": b"A\n"}, parent=None)
        artifact = tmp_path / "store" / "img"
        os.link(keep, artifact / "prod.json")
        assert keep.stat().st_nlink == 2

        store.promote("img", revision, to="prod")

        assert keep.read_bytes() == OUTSIDE
        assert keep.stat().st_nlink == 1
        assert store.read_tree("img", "prod") == {"a.txt": b"A\n"}
        assert _staging(artifact) == []

    def test_write_tree_leaves_a_hardlinked_sidecar_alone(self, tmp_path: Path) -> None:
        store, _, keep = _store(tmp_path)
        # The revision name is derived from the content, so a scratch store
        # gives the same one this call would write.
        revision = FileArtifactStore(tmp_path / "scratch").write_tree("img", {"a.txt": b"A\n"})
        artifact = tmp_path / "store" / "img"
        artifact.mkdir(parents=True)
        os.link(keep, artifact / f"{revision}.json")
        assert keep.stat().st_nlink == 2

        assert store.write_tree("img", {"a.txt": b"A\n"}) == revision

        assert keep.read_bytes() == OUTSIDE
        assert keep.stat().st_nlink == 1
        assert store.read_tree("img", revision) == {"a.txt": b"A\n"}
        assert _staging(artifact) == []
