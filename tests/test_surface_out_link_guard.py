"""The surface writers refuse a symlink planted at the destination (#1029).

``atomic_write_text`` backs every user-named output of the CLI surfaces and of
the MCP writers. It resolves the destination and ``os.replace``s over the leaf,
so a link named exactly like the destination was silently replaced by a regular
file while ``init``/``apply``/``demo`` refuse the same shape at exit 2
(#1008/#1020/#1021). The link is the operator's: it must survive, and so must
the bytes of whatever it points at.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentdescent import cli, mcp


def _planted(tmp_path: Path):
    """A work dir with ``out_link.json -> ../outside/keep.txt``."""
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "keep.txt"
    target.write_text("keep-me\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    link = work / "out_link.json"
    link.symlink_to(target)
    return work, link, target


def test_governed_harness_init_refuses_a_symlinked_out(tmp_path, capsys):
    work, link, target = _planted(tmp_path)

    code = cli.main(["governed-harness", "init", "--out", str(link)])

    captured = capsys.readouterr()
    assert code == 2
    # #1032/#1033 ship one ``error: <message>`` line for a SurfaceError, the
    # same envelope the ``cannot write`` writers use; the type prefix is gone.
    assert captured.err.strip() == (
        f"error: cannot write {link}: 'out_link.json' is a symlink")
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep-me\n"
    assert not list(work.glob(".agentdescent-surface-*"))


def test_governed_harness_init_refusal_is_ok_false_under_json(tmp_path, capsys):
    _work, link, target = _planted(tmp_path)

    code = cli.main(["governed-harness", "init", "--out", str(link), "--json"])

    captured = capsys.readouterr()
    assert code == 2
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"] == (
        f"cannot write {link}: 'out_link.json' is a symlink")
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep-me\n"


def test_a_plain_out_still_writes(tmp_path):
    out = tmp_path / "spec.json"

    assert cli.main(["governed-harness", "init", "--out", str(out)]) == 0

    assert json.loads(out.read_text(encoding="utf-8"))["artifact_id"]


def test_a_symlinked_directory_above_the_leaf_still_writes(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    out = alias / "spec.json"

    assert cli.main(["governed-harness", "init", "--out", str(out)]) == 0

    assert (real / "spec.json").is_file()
    assert out.is_file()


def test_the_mcp_ops_writer_refuses_the_same_leaf(tmp_path):
    from agentdescent.durable_runs import SqliteRunStore

    _work, link, target = _planted(tmp_path)
    runs_db = tmp_path / "runs.sqlite3"
    store = SqliteRunStore(str(runs_db))
    store.close()
    tools = mcp.Tools(surface_write_dirs=(str(tmp_path),))

    result = tools.ops(str(runs_db), "tenant", "workspace", out=str(link))

    assert result["ok"] is False
    assert result["error"].endswith(
        f"cannot write {link}: 'out_link.json' is a symlink")
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep-me\n"
