"""MCP apply must obey the same filesystem boundary as other write tools."""

import os
from pathlib import Path

import pytest

from agentdescent.durable_runs import SqliteRunStore
from agentdescent.mcp import Tools
from agentdescent.surface_common import SurfaceError, ensure_write_path
from tests.test_skill_library_apply_install import _make_library_run


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))


@pytest.mark.parametrize("destination", ["to", "install_to", "host", "stored"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_apply_refuses_outside_destinations(tmp_path, destination, dry_run):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    store, rid = _make_library_run(tmp_path)
    tools = Tools(store, surface_write_dirs=(str(allowed),))
    kwargs = {"run_id": rid, "dry_run": dry_run}
    outside = tmp_path / "outside"
    if destination == "host":
        kwargs.update(install_to="codex", home=str(outside))
    elif destination != "stored":
        kwargs[destination] = str(outside)
    result = tools.apply(**kwargs)
    assert "write allowlist" in result["error"]
    assert not outside.exists()
    assert "seed alpha" in (tmp_path / "seed-lib/alpha/SKILL.md").read_text()


def test_apply_empty_allowlist_and_allowed_file(tmp_path):
    src = tmp_path / "source.txt"
    src.write_text("new", encoding="utf-8")
    dest = tmp_path / "dest.txt"
    denied = Tools(surface_write_dirs=()).apply(source=str(src), to=str(dest))
    assert "write allowlist" in denied["error"]
    assert not dest.exists()
    dest.write_text("old", encoding="utf-8")
    allowed = Tools(surface_write_dirs=(str(tmp_path),))
    assert allowed.apply(source=str(src), to=str(dest), dry_run=True)["written"]
    assert dest.read_text() == "old"
    result = allowed.apply(source=str(src), to=str(dest))
    assert dest.read_text() == "new"
    assert Path(result["backup"][0]).read_text() == "old"


def test_apply_checks_backup_before_writing(tmp_path, monkeypatch):
    store, rid = _make_library_run(tmp_path)
    dest = tmp_path / "allowed"
    dest.mkdir()
    home = tmp_path / "outside-home"
    monkeypatch.setenv("AGENTDESCENT_HOME", str(home))
    tools = Tools(store, surface_write_dirs=(str(dest),))
    result = tools.apply(rid, to=str(dest))
    assert "write allowlist" in result["error"]
    assert not list(dest.iterdir())
    assert not home.exists()
    assert tools.apply(rid, to=str(dest), backup=False)["written"]


def _directory_link(link, target):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("operation", ["ops", "apply"])
def test_existing_directory_link_cannot_escape(tmp_path, operation):
    allowed, outside = tmp_path / "allowed", tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    link = allowed / "link"
    _directory_link(link, outside)
    try:
        tools = Tools(surface_write_dirs=(str(allowed),))
        if operation == "ops":
            db = allowed / "runs.sqlite3"
            SqliteRunStore(str(db)).close()
            result = tools.ops(str(db), "t", "w", out=str(link / "report.json"))
        else:
            src = tmp_path / "source"
            (src / "link").mkdir(parents=True)
            (src / "link/file.txt").write_text("candidate")
            result = tools.apply(source=str(src), to=str(allowed), backup=False)
        assert "write allowlist" in result["error"]
        assert not list(outside.iterdir())
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


def test_write_root_boundary_and_filesystem_root(tmp_path):
    allowed = tmp_path / "allowed"
    with pytest.raises(SurfaceError, match="write allowlist"):
        ensure_write_path(str(tmp_path / "allowed-sibling/file"), name="out",
                          allow=(str(allowed),))
    target = str(allowed / "file")
    assert ensure_write_path(target, name="out", allow=(tmp_path.anchor,)) == target


@pytest.mark.parametrize("tree", [False, True])
def test_apply_does_not_reload_the_source_after_checking_paths(tmp_path, monkeypatch, tree):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    src = tmp_path / "source"
    if tree:
        src.mkdir()
        (src / "first.txt").write_text("first", encoding="utf-8")
    else:
        src.write_text("first", encoding="utf-8")
    dest = allowed / ("tree" if tree else "result.txt")
    tools = Tools(surface_write_dirs=(str(allowed),))
    check = tools._check_write

    def change_source_after_planning(path, name):
        result = check(path, name)
        if str(path) == str(dest):
            if tree:
                (src / "later.txt").write_text("not planned", encoding="utf-8")
            else:
                src.write_text("not planned", encoding="utf-8")
        return result

    monkeypatch.setattr(tools, "_check_write", change_source_after_planning)
    result = tools.apply(source=str(src), to=str(dest), backup=False)
    assert "error" not in result
    if tree:
        assert result["written"] == ["first.txt"]
        assert sorted(p.name for p in dest.iterdir()) == ["first.txt"]
    else:
        assert dest.read_text(encoding="utf-8") == "first"
