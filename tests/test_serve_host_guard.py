"""`serve --host` must not publish the run panel without an opt-in (#911).

`agentdescent serve --host 0.0.0.0` forwarded the host straight into the
runstore bind: the panel has no authentication and lists every run in the
store, so a single flag published it to the network. `agentdescent mcp` already
refuses the same bind without `--allow-remote` and exits 2; `serve` matches it.

The tests spy on `runstore.serve_http`, so they bind no port and need no
network: "binds nothing" is asserted as "the binder was never called".
"""

import argparse
import json

import pytest

from agentdescent import cli, runstore


def _args(host="127.0.0.1", port=0, *, as_json=False, allow_remote=None):
    ns = argparse.Namespace(host=host, port=port, store=None)
    if as_json:
        ns.json = True
    if allow_remote is not None:
        ns.allow_remote = allow_remote
    return ns


@pytest.fixture
def binds(monkeypatch):
    """Record `runstore.serve_http` calls instead of binding a port."""
    calls = []

    def fake(host=None, port=0, store=None, serve_forever=True):
        calls.append((host, port))

        class Panel:
            server_address = (host, 1234)

            def serve_forever(self):
                pass

            def server_close(self):
                pass

        return Panel()

    monkeypatch.setattr(runstore, "serve_http", fake)
    return calls


def test_a_non_loopback_host_without_the_flag_is_refused(binds, capsys):
    assert cli.cmd_serve(_args("0.0.0.0")) == 2
    assert binds == []
    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("\n") == 1, err
    assert "refusing" in err and "0.0.0.0" in err and "Traceback" not in err


def test_the_refusal_is_json_under_json(binds, capsys):
    assert cli.cmd_serve(_args("0.0.0.0", as_json=True)) == 2
    assert binds == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False and "refusing" in payload["error"]


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_hosts_bind_as_before(binds, capsys, host):
    assert cli.cmd_serve(_args(host)) == 0
    assert binds == [(host, 0)]


def test_the_opt_in_serves_a_non_loopback_host_with_a_warning(binds, capsys):
    assert cli.cmd_serve(_args("0.0.0.0", allow_remote=True)) == 0
    assert binds == [("0.0.0.0", 0)]
    err = capsys.readouterr().err
    assert "WARNING" in err and "no authentication" in err


def test_the_serve_parser_accepts_the_opt_in():
    args = cli.build_parser().parse_args(
        ["serve", "--host", "0.0.0.0", "--allow-remote"])
    assert args.allow_remote is True and args.host == "0.0.0.0"
