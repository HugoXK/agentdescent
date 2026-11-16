"""The skill-library seed refuses an unwritable target in one line (#1003).

`#990`/`#995` wrapped the `init` / `apply` artifact writers, but the starters
seeded by `ensure_skill_library_tree` still wrote raw, and the seed ran *before*
the wrapped `--out` writer: an unwritable target traced back, and a refused
`--out` left the seeded `*/SKILL.md` behind. Offline, no model, no port; the
structural cases fail on any uid, so a root CI leg cannot turn them into a
silent pass.
"""

from __future__ import annotations

import json

import pytest

from agentdescent import cli

from tests.test_cli_write_error import _assert_refusal, _argv, _blocked

MODES = [pytest.param(False, id="text"), pytest.param(True, id="json")]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))


def _target(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    return root


def _skill_md(root):
    return sorted(p.parent.name for p in root.glob("*/SKILL.md"))


def _permissions_are_enforced(tmp_path):
    """A root CI leg ignores `0500`, so that case would pass for the wrong reason."""
    probe = tmp_path / "perm-probe"
    probe.mkdir()
    try:
        probe.chmod(0o500)
        try:
            (probe / "x").write_text("x", encoding="utf-8")
        except OSError:
            return True
        return False
    finally:
        probe.chmod(0o700)


@pytest.mark.parametrize("as_json", MODES)
def test_init_seed_into_a_read_only_target_is_one_line(tmp_path, capsys, as_json):
    if not _permissions_are_enforced(tmp_path):
        pytest.skip("this uid ignores directory permissions (root CI leg)")
    target = _target(tmp_path)
    target.chmod(0o500)
    try:
        rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                            "--agent", "cli_agent", "--out", str(tmp_path / "s.json")))
    finally:
        target.chmod(0o700)
    assert rc == 2
    _assert_refusal(capsys, as_json, path=target / "example-alpha")
    assert _skill_md(target) == []


@pytest.mark.parametrize("as_json", MODES)
def test_init_seed_blocked_by_a_regular_file_is_one_line(tmp_path, capsys, as_json):
    target = _target(tmp_path)
    blocker = target / "example-alpha"
    blocker.write_text("not a directory\n", encoding="utf-8")
    rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                        "--agent", "cli_agent", "--out", str(tmp_path / "s.json")))
    assert rc == 2
    _assert_refusal(capsys, as_json, path=blocker)
    assert _skill_md(target) == [] and not (tmp_path / "s.json").exists()


@pytest.mark.parametrize("as_json", MODES)
def test_algorithms_run_seed_refusal_is_one_line(tmp_path, capsys, as_json):
    target = _target(tmp_path)
    blocker = target / "example-alpha"
    blocker.write_text("not a directory\n", encoding="utf-8")
    rc = cli.main(_argv(as_json, "algorithms", "run", "evoskill", str(target),
                        "--kind", "skill_library", "--out", str(tmp_path / "s.json")))
    assert rc == 2
    _assert_refusal(capsys, as_json, path=blocker)
    assert _skill_md(target) == []


@pytest.mark.parametrize("as_json", MODES)
def test_a_writable_target_with_an_unwritable_out_seeds_nothing(tmp_path, capsys,
                                                               as_json):
    """Criterion 3: the `--out` refusal is checked before the seed writes."""
    target = _target(tmp_path)
    out = _blocked(tmp_path) / "spec.json"
    rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                        "--agent", "cli_agent", "--out", str(out)))
    assert rc == 2
    _assert_refusal(capsys, as_json, path=out)
    assert sorted(p.name for p in target.iterdir()) == []


@pytest.mark.parametrize("as_json", MODES)
def test_a_refused_spec_backup_leaves_no_seeded_starters(tmp_path, capsys, as_json):
    """A 250-character spec name makes its `.bak-0` sibling 256, over `NAME_MAX`."""
    target = _target(tmp_path)
    out = tmp_path / ("s" * 250)
    out.write_text('{"stale": true}\n', encoding="utf-8")
    rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                        "--agent", "cli_agent", "--out", str(out),
                        "--model", "echo"))
    assert rc == 2
    _assert_refusal(capsys, as_json, path=out)
    assert sorted(p.name for p in target.iterdir()) == []


def test_a_writable_target_still_seeds_both_starters(tmp_path, capsys):
    target = _target(tmp_path)
    assert cli.main(["init", str(target), "--kind", "skill_library",
                     "--agent", "cli_agent", "--out", str(tmp_path / "s.json")]) == 0
    assert _skill_md(target) == ["example-alpha", "example-beta"]
    assert "seeded" in capsys.readouterr().out


# --- destination links (#1008) -------------------------------------------
#
# `_preflight_write` tested writability only and `write_starter_spec` never
# looked at the `--out` leaf, so every one of these followed the link: the spec
# was written outside the target tree and a `.bak-N` inside the tree held the
# outside file's bytes. `filetree.dest_problem` is the rule `apply` already
# uses (#977); these assert it on the seed writer and the spec writers.


def _outside(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    return outside


def _link(path, to):
    path.symlink_to(to)
    return path


def _no_backups(root):
    return sorted(p.name for p in root.rglob("*.bak-*"))


def _assert_link_refusal(capsys, as_json, path):
    """The refusal names the link, not `File exists` (#1008)."""
    cap = capsys.readouterr()
    assert "Traceback" not in cap.err and "Traceback" not in cap.out
    if as_json:
        doc = json.loads(cap.out)
        assert doc["ok"] is False and doc["error"]
        text = doc["error"]
    else:
        lines = [ln for ln in cap.err.strip().splitlines() if ln]
        assert len(lines) == 1, cap.err
        text = lines[0]
    assert text.startswith("error: cannot write ") or text.startswith("cannot write "), text
    assert str(path) in text and "is a symlink" in text, text


@pytest.mark.parametrize("as_json", MODES)
def test_a_symlinked_starter_dir_is_refused(tmp_path, capsys, as_json):
    target = _target(tmp_path)
    outside = _outside(tmp_path)
    (outside / "example-alpha").mkdir()
    _link(target / "example-alpha", outside / "example-alpha")
    rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                        "--agent", "cli_agent", "--out", str(tmp_path / "s.json")))
    assert rc == 2
    _assert_link_refusal(capsys, as_json, target / "example-alpha")
    assert sorted(p.name for p in (outside / "example-alpha").iterdir()) == []
    assert _skill_md(target) == []


@pytest.mark.parametrize("as_json", MODES)
def test_algorithms_run_symlinked_starter_dir_is_refused(tmp_path, capsys, as_json):
    target = _target(tmp_path)
    outside = _outside(tmp_path)
    (outside / "example-alpha").mkdir()
    _link(target / "example-alpha", outside / "example-alpha")
    rc = cli.main(_argv(as_json, "algorithms", "run", "evoskill", str(target),
                        "--kind", "skill_library", "--out", str(tmp_path / "s.json")))
    assert rc == 2
    _assert_link_refusal(capsys, as_json, target / "example-alpha")
    assert sorted(p.name for p in (outside / "example-alpha").iterdir()) == []
    assert _skill_md(target) == []


@pytest.mark.parametrize("kind", ["text", "skill_library"])
@pytest.mark.parametrize("dangling", [False, True], ids=["existing", "dangling"])
@pytest.mark.parametrize("as_json", MODES)
def test_a_symlinked_out_is_refused(tmp_path, capsys, as_json, kind, dangling):
    outside = _outside(tmp_path)
    secret = outside / "secret.txt"
    secret.write_text("SECRET-OUTSIDE-BYTES\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    _link(out, secret if not dangling else outside / "created.txt")
    if kind == "text":
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("prompt body\n", encoding="utf-8")
        args = ["init", str(prompt), "--kind", "text", "--out", str(out)]
    else:
        args = ["init", str(_target(tmp_path)), "--kind", "skill_library",
                "--agent", "cli_agent", "--out", str(out)]
    rc = cli.main(_argv(as_json, *args))
    assert rc == 2
    _assert_link_refusal(capsys, as_json, out)
    assert secret.read_text(encoding="utf-8") == "SECRET-OUTSIDE-BYTES\n"
    assert not (outside / "created.txt").exists()
    assert _no_backups(tmp_path) == []
    if kind == "skill_library":
        assert _skill_md(tmp_path / "library") == []


@pytest.mark.parametrize("as_json", MODES)
def test_a_symlinked_providers_file_is_refused(tmp_path, capsys, as_json):
    target = _target(tmp_path)
    outside = _outside(tmp_path)
    secret = outside / "oc.json"
    secret.write_text("SECRET-OUTSIDE-BYTES\n", encoding="utf-8")
    _link(tmp_path / "spec.opencode-providers.json", secret)
    rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                        "--out", str(tmp_path / "spec.json"), "--agent", "opencode",
                        "--model", "gpt-4o-mini",
                        "--base-url", "http://127.0.0.1:1/v1"))
    assert rc == 2
    _assert_link_refusal(capsys, as_json, tmp_path / "spec.opencode-providers.json")
    assert secret.read_text(encoding="utf-8") == "SECRET-OUTSIDE-BYTES\n"
    assert _no_backups(tmp_path) == []
    assert _skill_md(target) == []


def test_a_normal_out_still_backs_up(tmp_path, capsys):
    target = _target(tmp_path)
    out = tmp_path / "s.json"
    out.write_text('{"stale": true}\n', encoding="utf-8")
    assert cli.main(["init", str(target), "--kind", "skill_library",
                     "--agent", "cli_agent", "--out", str(out)]) == 0
    assert (tmp_path / "s.json.bak-0").exists()
    assert _skill_md(target) == ["example-alpha", "example-beta"]


def test_a_symlinked_parent_directory_is_still_allowed(tmp_path, capsys):
    real = tmp_path / "real"
    real.mkdir()
    linked = _link(tmp_path / "linked", real)
    target = linked / "library"
    target.mkdir()
    assert cli.main(["init", str(target), "--kind", "skill_library",
                     "--agent", "cli_agent", "--out", str(tmp_path / "s.json")]) == 0
    assert _skill_md(real / "library") == ["example-alpha", "example-beta"]
