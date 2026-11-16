"""``capability init`` refuses a link planted at either fixture leaf (#1043).

The writer owns two leaves under ``--out``'s directory: ``spec.json`` through
``atomic_write_json`` (already guarded, #1031) and ``capability-traces.jsonl``
through a plain ``open(..., "w")`` in the ``--demo`` branch -- unguarded, so a
link named exactly like it was dereferenced and the linked file destroyed. The
traces are written before the spec, so the ``--out`` refusal also left a
452-byte fixture behind. Both leaves are now checked with
``filetree.dest_problem`` before the first byte, the rule ``demo.py`` already
follows (#1017/#1021): refuse the link, keep its bytes, write no fixture.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from agentdescent import cli

ORIGINAL = "ORIGINAL-OUTSIDE-BYTES"


def _planted(tmp_path: Path, leaf: str):
    """An ``out/`` directory with ``<leaf> -> ../outside/keep.json``."""
    outside = tmp_path / "outside"
    outside.mkdir()
    keep = outside / "keep.json"
    keep.write_text(ORIGINAL, encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    link = out_dir / leaf
    link.symlink_to(keep)
    return out_dir, link, keep


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestCapabilityInitLeafGuard:
    def test_a_link_at_the_traces_leaf_is_refused_before_it_is_written(self, tmp_path, capsys):
        out_dir, link, keep = _planted(tmp_path, "capability-traces.jsonl")
        before = _sha(keep)

        code = cli.main(["capability", "init", "--demo",
                         "--out", str(out_dir / "spec.json")])

        captured = capsys.readouterr()
        assert code == 2
        assert captured.err.strip() == (
            f"error: cannot write {link}: 'capability-traces.jsonl' is a symlink")
        assert link.is_symlink()
        assert _sha(keep) == before
        assert keep.read_text(encoding="utf-8") == ORIGINAL
        assert not (out_dir / "spec.json").exists()

    def test_a_link_at_the_out_leaf_writes_no_traces_fixture(self, tmp_path, capsys):
        out_dir, link, keep = _planted(tmp_path, "spec.json")
        before = _sha(keep)

        code = cli.main(["capability", "init", "--demo", "--out", str(link)])

        captured = capsys.readouterr()
        assert code == 2
        assert captured.err.strip() == (
            f"error: cannot write {link}: 'spec.json' is a symlink")
        assert link.is_symlink()
        assert _sha(keep) == before
        assert not (out_dir / "capability-traces.jsonl").exists()

    def test_a_plain_out_writes_both_leaves(self, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        code = cli.main(["capability", "init", "--demo",
                         "--out", str(out_dir / "spec.json")])

        assert code == 0
        spec = (out_dir / "spec.json").read_text(encoding="utf-8")
        traces = out_dir / "capability-traces.jsonl"
        assert traces.is_file()
        assert len(traces.read_text(encoding="utf-8").splitlines()) == 4
        assert str(traces) in spec

    def test_without_demo_a_link_at_the_traces_leaf_is_left_alone(self, tmp_path):
        out_dir, link, keep = _planted(tmp_path, "capability-traces.jsonl")
        before = _sha(keep)

        code = cli.main(["capability", "init", "--out", str(out_dir / "spec.json")])

        assert code == 0
        assert link.is_symlink()
        assert _sha(keep) == before
        assert (out_dir / "spec.json").is_file()

    def test_a_symlinked_directory_above_the_leaf_still_writes(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(real, target_is_directory=True)

        code = cli.main(["capability", "init", "--demo",
                         "--out", str(alias / "spec.json")])

        assert code == 0
        assert (real / "spec.json").is_file()
        assert (real / "capability-traces.jsonl").is_file()

    def test_a_hardlink_at_the_traces_leaf_keeps_the_outside_bytes(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        keep = outside / "keep.json"
        keep.write_text(ORIGINAL, encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        leaf = out_dir / "capability-traces.jsonl"
        os.link(keep, leaf)

        code = cli.main(["capability", "init", "--demo",
                         "--out", str(out_dir / "spec.json")])

        assert code == 0
        assert keep.read_text(encoding="utf-8") == ORIGINAL
        assert leaf.is_file() and not leaf.is_symlink()
        assert leaf.stat().st_nlink == 1
        assert len(leaf.read_text(encoding="utf-8").splitlines()) == 4
        assert not list(out_dir.glob(".staging-*"))

    def test_a_directory_at_the_traces_leaf_is_refused_before_any_byte(self, tmp_path, capsys):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        leaf = out_dir / "capability-traces.jsonl"
        leaf.mkdir()

        code = cli.main(["capability", "init", "--demo",
                         "--out", str(out_dir / "spec.json")])

        captured = capsys.readouterr()
        assert code == 2
        assert captured.err.strip() == f"error: cannot write {leaf}: not a file"
        assert leaf.is_dir()
        assert not (out_dir / "spec.json").exists()
        assert [p.name for p in out_dir.iterdir()] == ["capability-traces.jsonl"]

    def test_an_interrupt_while_staging_leaves_no_staging_file(self, tmp_path, monkeypatch):
        from agentdescent import surface_capability

        calls = {"n": 0}

        def interrupting(payload):
            calls["n"] += 1
            if calls["n"] == 3:
                raise KeyboardInterrupt
            return '{"trace_id": "demo"}\n'

        monkeypatch.setattr(surface_capability, "json_line", interrupting)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        with pytest.raises(KeyboardInterrupt):
            surface_capability.capability_init(str(out_dir / "spec.json"), demo=True)

        assert not list(out_dir.glob(".staging-*"))

    def test_the_staged_traces_are_fsynced_before_the_rename(self, tmp_path, monkeypatch):
        from agentdescent import surface_capability

        events = []
        real_fsync = os.fsync
        real_replace = os.replace

        def recording_fsync(fd):
            events.append(("fsync", fd))
            return real_fsync(fd)

        def recording_replace(src, dst):
            events.append(("replace", str(src), str(dst)))
            return real_replace(src, dst)

        monkeypatch.setattr(surface_capability.os, "fsync", recording_fsync)
        monkeypatch.setattr(surface_capability.os, "replace", recording_replace)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        payload = surface_capability.capability_init(str(out_dir / "spec.json"), demo=True)

        assert payload["ok"] is True
        last_fsync = -1
        for index, event in enumerate(events):
            if event[0] == "fsync":
                last_fsync = index
                continue
            if event[0] == "replace" and ".staging-" in os.path.basename(event[1]):
                assert last_fsync != -1 and last_fsync < index

    def test_an_existing_directory_at_out_writes_no_traces_fixture(self, tmp_path, capsys):
        parent = tmp_path / "fixture"
        parent.mkdir()
        target = parent / "out"
        target.mkdir()

        code = cli.main(["capability", "init", "--demo", "--out", str(target)])

        captured = capsys.readouterr()
        assert code == 2
        assert captured.err.strip().startswith("error: ")
        assert sorted(p.name for p in parent.iterdir()) == ["out"]
        assert list(target.iterdir()) == []
