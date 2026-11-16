"""A SurfaceError prints as one `error: <message>` line, like the sibling writers.

The `cannot write` family (#1008, #1017, #1015) prints `error: cannot write
<path>: <reason>` with no exception class, and its tests pin that shape. The
product surfaces went through ``_surface_error``, which prefixed the class:
`error: SurfaceError: runs_db '<path>' does not exist`. A script that matches
the documented line misses every surface refusal, including the symlink
refusals the family just gained (#1020, #1021, #1029).
"""
import argparse

from agentdescent import cli


def _missing(tmp_path, name):
    return str(tmp_path / name)


def test_platform_refusal_is_one_unprefixed_line(tmp_path, capsys):
    rc = cli.main(["--store", str(tmp_path / "runs"), "platform", "status",
                   "--runs-db", _missing(tmp_path, "nope.db")])

    err = capsys.readouterr().err
    assert rc == 2
    assert err.count("error:") == 1
    assert err.startswith("error: runs_db ")
    assert "SurfaceError:" not in err
    assert "does not exist" in err


def test_ops_refusal_is_one_unprefixed_line(tmp_path, capsys):
    rc = cli.main(["--store", str(tmp_path / "runs"), "ops", "plan",
                   "--runs-db", _missing(tmp_path, "nope.db"),
                   "--tenant", "t", "--workspace", "w"])

    err = capsys.readouterr().err
    assert rc == 2
    assert err.startswith("error: runs_db ")
    assert "SurfaceError:" not in err


def test_json_error_field_carries_the_same_unprefixed_message(tmp_path, capsys):
    rc = cli.main(["--store", str(tmp_path / "runs"), "tenant", "plan",
                   "--spec", _missing(tmp_path, "nope.json"), "--json"])

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    payload = __import__("json").loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"].startswith("tenant spec ")
    assert "SurfaceError:" not in payload["error"]


def test_another_exception_keeps_its_class_prefix(capsys):
    """The prefix is diagnostic for anything that is not a product refusal."""
    a = argparse.Namespace(json=False)

    assert cli._surface_error(a, ValueError("boom")) == 2
    assert capsys.readouterr().err == "error: ValueError: boom\n"


def test_debug_environment_still_reraises(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_DEBUG", "1")
    a = argparse.Namespace(json=False)

    try:
        cli._surface_error(a, __import__("agentdescent.surface_common",
                                        fromlist=["SurfaceError"]).SurfaceError("nope"))
    except Exception as error:                     # noqa: BLE001 - the point of the test
        assert type(error).__name__ == "SurfaceError"
    else:                                          # pragma: no cover - the guard
        raise AssertionError("AGENTDESCENT_DEBUG must re-raise a SurfaceError")
