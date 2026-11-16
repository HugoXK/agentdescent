"""A refused artifact write is one `error:` line, not a traceback (#990).

`init --out`, `algorithms run --out` and `apply --to` write outside the run
store, and `main()` catches only `(SpecError, RunStoreError)`, so a bare
`OSError` from the writer escaped as a traceback. `#907` already gave the run
store that contract (`error: cannot create run store <path>: <reason>`, or
`{"ok": false, "error": ...}` under `--json`); these are the artifact writers.
"""

from __future__ import annotations

import json
import os

import pytest

from agentdescent import cli, runstore
from agentdescent.evolution import EvolutionResult
from agentdescent.filetree import canonical
from agentdescent.evolvespec import EvolveSpec

from tests.test_skill_library_apply_install import _make_library_run

MODES = [pytest.param(False, id="text"), pytest.param(True, id="json")]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))


def _blocked(tmp_path):
    """A path whose parent is a regular file: unwritable whatever the uid."""
    p = tmp_path / "blocked"
    p.write_text("not a directory\n", encoding="utf-8")
    return p


def _argv(as_json, *args):
    return (["--json"] if as_json else []) + list(args)


def _assert_refusal(capsys, as_json, *, path=None, prefix="cannot write "):
    cap = capsys.readouterr()
    assert "Traceback" not in cap.err and "Traceback" not in cap.out
    if as_json:
        # One machine-readable document on stdout, nothing else (#990).
        doc = json.loads(cap.out)
        assert doc["ok"] is False and doc["error"]
        assert doc["error"].startswith(prefix)
        if path is not None:
            assert str(path) in doc["error"]
    else:
        assert cap.out == ""
        lines = [ln for ln in cap.err.strip().splitlines() if ln]
        assert len(lines) == 1, cap.err
        assert lines[0].startswith("error: " + prefix)
        if path is not None:
            assert str(path) in lines[0]


def _text_run(tmp_path):
    """One completed offline text-kind run in an isolated store."""
    store = str(tmp_path / "runs-text")
    rd = runstore.create(EvolveSpec(
        kind="text", target=str(tmp_path / "rule.md"),
        data={"inline": [{"prompt": "p", "gold": "g"}]}, score="exact",
        agent="echo", reflect="echo").to_dict(), store=store)
    EvolutionResult(state={}, rendered="evolved rule\n", final_reward=0.0,
                    history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    return store, rd.run_id


@pytest.mark.parametrize("as_json", MODES)
def test_init_out_that_cannot_be_written(tmp_path, capsys, as_json):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "rule.md").write_text("Be helpful.\n", encoding="utf-8")
    out = _blocked(tmp_path) / "spec.json"
    assert cli.main(_argv(as_json, "init", str(proj), "--out", str(out))) == 2
    _assert_refusal(capsys, as_json, path=out)


@pytest.mark.parametrize("as_json", MODES)
def test_algorithms_run_out_that_cannot_be_written(tmp_path, capsys, as_json):
    target = tmp_path / "rule.md"
    target.write_text("Be helpful.\n", encoding="utf-8")
    blocked = _blocked(tmp_path)
    out = blocked / "algo.json"
    assert cli.main(_argv(as_json, "algorithms", "run", "archive_selection",
                          str(target), "--out", str(out))) == 2
    _assert_refusal(capsys, as_json, path=out)


@pytest.mark.parametrize("as_json", MODES)
def test_apply_tree_to_a_destination_that_cannot_be_created(tmp_path, capsys,
                                                           as_json):
    store, rid = _make_library_run(tmp_path)
    dest = _blocked(tmp_path) / "newdir"
    assert cli.main(_argv(as_json, "--store", store, "apply", rid,
                          "--to", str(dest))) == 2
    _assert_refusal(capsys, as_json, path=dest)


@pytest.mark.parametrize("as_json", MODES)
def test_apply_text_to_a_destination_that_cannot_be_written(tmp_path, capsys,
                                                           as_json):
    store, rid = _text_run(tmp_path)
    dest = _blocked(tmp_path) / "out.txt"
    assert cli.main(_argv(as_json, "--store", store, "apply", rid,
                          "--to", str(dest))) == 2
    _assert_refusal(capsys, as_json, path=dest)


@pytest.mark.parametrize("as_json", MODES)
def test_default_store_under_an_unwritable_home_is_one_line(tmp_path, capsys,
                                                            monkeypatch, as_json):
    """The #907 shape stands: one line, exit 2, no traceback."""
    blocked = _blocked(tmp_path)
    monkeypatch.delenv("AGENTDESCENT_HOME", raising=False)
    monkeypatch.setenv("HOME", str(blocked))
    assert cli.main(_argv(as_json, "apply", "latest", "--to",
                          str(tmp_path / "out"))) == 2
    _assert_refusal(capsys, as_json, prefix="")


def test_a_writable_destination_still_writes_the_same_bytes(tmp_path, capsys):
    store, rid = _text_run(tmp_path)
    dest = tmp_path / "out.txt"
    assert cli.main(["--store", store, "apply", rid, "--to", str(dest)]) == 0
    assert dest.read_text(encoding="utf-8") == "evolved rule\n"


@pytest.mark.parametrize("as_json", MODES)
def test_init_over_an_existing_spec_that_cannot_be_backed_up(tmp_path, capsys,
                                                            as_json):
    """The ``.bak-N`` copy runs before the wrapped ``open(out)`` (#994).

    A 250-character file name is legal and its ``.bak-0`` sibling is 256, over
    ``NAME_MAX``, so the backup is refused structurally: no permissions, no
    uid, and the case cannot turn into a skip in a root CI leg.
    """
    proj = tmp_path / "proj-bak"
    proj.mkdir()
    (proj / "rule.md").write_text("Be helpful.\n", encoding="utf-8")
    out = tmp_path / ("s" * 250)
    out.write_text('{"stale": true}\n', encoding="utf-8")
    assert cli.main(_argv(as_json, "init", str(proj), "--out", str(out),
                          "--model", "echo")) == 2
    _assert_refusal(capsys, as_json, path=out)


@pytest.mark.parametrize("as_json", MODES)
def test_apply_from_a_file_into_a_parent_that_cannot_be_created(tmp_path,
                                                                capsys, as_json):
    src = tmp_path / "rule.md"
    src.write_text("evolved\n", encoding="utf-8")
    dest = _blocked(tmp_path) / "out.txt"
    assert cli.main(_argv(as_json, "apply", "--from", str(src),
                          "--to", str(dest))) == 2
    _assert_refusal(capsys, as_json, path=dest)


@pytest.mark.parametrize("as_json", MODES)
def test_apply_from_a_tree_into_a_destination_that_cannot_be_created(
        tmp_path, capsys, as_json):
    src = tmp_path / "skill"
    src.mkdir()
    (src / "SKILL.md").write_text("evolved\n", encoding="utf-8")
    dest = _blocked(tmp_path) / "newdir"
    assert cli.main(_argv(as_json, "apply", "--from", str(src),
                          "--to", str(dest))) == 2
    _assert_refusal(capsys, as_json, path=dest)
