"""#906: a bare `demo` must not leave `agentdescent-demo-*` roots behind.

The default root is a `tempfile.mkdtemp(prefix="agentdescent-demo-")` and nothing
removed it, so every bare run (success or failure) leaked a directory while
`docs/plugin-quickstart.md` told users only `--dir` kept anything.
"""

from __future__ import annotations

import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from agentdescent import cli, runstore


def _run(tmp_path, monkeypatch, *extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENTDESCENT_HOME", str(home))
    # `tempfile` caches `tempdir`; point the demo's mkdtemp at the test dir.
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir(exist_ok=True)
    monkeypatch.setattr(tempfile, "tempdir", str(tmpdir))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--store", str(tmp_path / "runs"), "demo", *extra])
    return code, buf.getvalue(), tmpdir


def _demo_roots(tmpdir):
    return sorted(p.name for p in tmpdir.glob("agentdescent-demo-*"))


def test_two_bare_runs_leave_no_demo_root(tmp_path, monkeypatch):
    first, out1, tmpdir = _run(tmp_path, monkeypatch)
    assert first == 0, out1
    second, out2, _ = _run(tmp_path, monkeypatch)
    assert second == 0, out2
    assert _demo_roots(tmpdir) == [], _demo_roots(tmpdir)
    # the human line must say the directory does not survive the run
    assert "(removed at exit)" in out1, out1


def test_dir_still_keeps_the_root(tmp_path, monkeypatch):
    work = tmp_path / "work"
    code, out, tmpdir = _run(tmp_path, monkeypatch, "--dir", str(work))
    assert code == 0, out
    assert (work / "cases.jsonl").is_file()
    assert _demo_roots(tmpdir) == []
    assert "removed at exit" not in out, out


def test_json_reports_a_root_that_still_exists(tmp_path, monkeypatch):
    code, out, _ = _run(tmp_path, monkeypatch, "--json")
    assert code == 0, out
    payload = json.loads(out)
    root = Path(payload["dir"])
    assert root.name.startswith("agentdescent-demo-"), payload["dir"]
    assert root.is_dir(), payload["dir"]


def test_a_failed_run_also_removes_the_default_root(tmp_path, monkeypatch):
    def boom(rd):
        raise runstore.RunStoreError("simulated failure")

    monkeypatch.setattr(runstore, "execute", boom)
    code, out, tmpdir = _run(tmp_path, monkeypatch)
    assert code == 2, out
    assert _demo_roots(tmpdir) == [], _demo_roots(tmpdir)


@pytest.mark.parametrize("kind", ["text", "skill_dir"])
def test_every_kind_cleans_up(tmp_path, monkeypatch, kind):
    code, out, tmpdir = _run(tmp_path, monkeypatch, "--kind", kind)
    assert code == 0, out
    assert _demo_roots(tmpdir) == [], _demo_roots(tmpdir)


@pytest.mark.parametrize("kind", ["skill_dir", "text", "skill_library"])
def test_a_bare_demo_does_not_recommend_show_or_apply(tmp_path, monkeypatch, kind):
    """#1047: the footer named `show`/`apply` for a directory that is gone.

    A bare run deletes its root at exit (#906), so `show` rendered the whole
    artifact as new and `apply` would rebuild a directory that no longer
    existed. Point the reader at `--dir` instead, and never print a command
    against a path this run just removed.
    """
    code, out, _ = _run(tmp_path, monkeypatch, "--kind", kind)
    assert code == 0, out
    assert "agentdescent show" not in out, out
    assert "agentdescent apply" not in out, out
    assert "agentdescent demo --dir" in out, out


def test_a_kept_demo_still_prints_show_and_apply(tmp_path, monkeypatch):
    """The control: `--dir` keeps the root, so those two steps are real."""
    work = tmp_path / "work"
    code, out, _ = _run(tmp_path, monkeypatch, "--dir", str(work))
    assert code == 0, out
    assert "agentdescent show" in out, out
    assert "agentdescent apply" in out, out
    assert "agentdescent demo --dir" not in out, out
