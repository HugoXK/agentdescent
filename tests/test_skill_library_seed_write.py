"""An unwritable skill-library seed is one `error:` line, not a traceback (#1003).

`#990`/`#995` wrapped the `--out`/`--to` artifact writers. `ensure_skill_library_tree`
still wrote raw, and it runs before the `--out` makedirs, so an unwritable target
— or a writable target with an unwritable `--out` — escaped as a traceback and
could leave a half-seeded tree behind.
"""

from __future__ import annotations

import json
import os

import pytest

from agentdescent import cli

MODES = [pytest.param(False, id="text"), pytest.param(True, id="json")]
NOT_ROOT = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="a 0500 directory is writable for uid 0, so the refusal cannot be probed")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)


def _blocked(tmp_path):
    """A path whose parent is a regular file: unwritable whatever the uid."""
    p = tmp_path / "blocked"
    p.write_text("not a directory\n", encoding="utf-8")
    return p


def _readonly(tmp_path):
    """An existing target directory no non-root process can create a child in."""
    root = tmp_path / "ro-library"
    root.mkdir()
    root.chmod(0o500)
    return root


def _seeded(root):
    return sorted(p.name for p in root.glob("*/SKILL.md"))


def _assert_refusal(capsys, as_json, path):
    cap = capsys.readouterr()
    assert "Traceback" not in cap.err and "Traceback" not in cap.out
    if as_json:
        doc = json.loads(cap.out)
        assert doc["ok"] is False and doc["error"]
        assert doc["error"].startswith(f"cannot write {path}")
    else:
        assert cap.out == ""
        lines = [ln for ln in cap.err.strip().splitlines() if ln]
        assert len(lines) == 1, cap.err
        assert lines[0].startswith(f"error: cannot write {path}")


@NOT_ROOT
@pytest.mark.parametrize("as_json", MODES)
def test_init_on_an_unwritable_skill_library_target(tmp_path, capsys, as_json):
    target = _readonly(tmp_path)
    argv = (["--json"] if as_json else []) + [
        "init", str(target), "--kind", "skill_library",
        "--agent", "cli_agent", "--out", str(tmp_path / "spec.json")]
    assert cli.main(argv) == 2
    _assert_refusal(capsys, as_json, target / "example-alpha")


@NOT_ROOT
@pytest.mark.parametrize("as_json", MODES)
def test_algorithms_run_on_an_unwritable_skill_library_target(tmp_path, capsys,
                                                              as_json):
    target = _readonly(tmp_path)
    argv = (["--json"] if as_json else []) + [
        "algorithms", "run", "archive_selection", str(target),
        "--kind", "skill_library", "--agent", "cli_agent",
        "--out", str(tmp_path / "spec.json")]
    assert cli.main(argv) == 2
    _assert_refusal(capsys, as_json, target / "example-alpha")


def test_init_refuses_before_seeding_when_out_cannot_be_written(tmp_path, capsys):
    """The `--out` preflight runs before the seed, so a refusal leaves no tree."""
    target = tmp_path / "library"
    target.mkdir()
    out = _blocked(tmp_path) / "spec.json"
    assert cli.main(["init", str(target), "--kind", "skill_library",
                     "--agent", "cli_agent", "--out", str(out)]) == 2
    _assert_refusal(capsys, False, out)
    assert _seeded(target) == []


def test_a_seed_that_cannot_create_its_folder_is_one_line(tmp_path, capsys):
    """Uid-independent: a regular file named like a starter blocks `makedirs`."""
    target = tmp_path / "library"
    target.mkdir()
    (target / "example-alpha").write_text("not a folder\n", encoding="utf-8")
    assert cli.main(["init", str(target), "--kind", "skill_library",
                     "--agent", "cli_agent",
                     "--out", str(tmp_path / "spec.json")]) == 2
    _assert_refusal(capsys, False, target / "example-alpha")
    assert _seeded(target) == []
    assert not (tmp_path / "spec.json").exists()


def test_a_writable_target_still_seeds_and_exits_zero(tmp_path, capsys):
    target = tmp_path / "library"
    target.mkdir()
    assert cli.main(["init", str(target), "--kind", "skill_library",
                     "--agent", "cli_agent",
                     "--out", str(tmp_path / "spec.json")]) == 0
    assert len(_seeded(target)) == 2
    assert (tmp_path / "spec.json").is_file()
