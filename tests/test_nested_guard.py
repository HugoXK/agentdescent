"""A worker must not start a nested run: refuse, and name the reason (#963).

``runners._child_env`` sets ``AGENTDESCENT_NESTED=1`` in every host worker it
spawns, and the MCP ``start`` tool already answered it with a refused stub. The
CLI never read the marker, so `agentdescent evolve` inside a worker started a
second run on a machine already running one -- recursion by another name.
"""

from __future__ import annotations

import json

from agentdescent import cli, mcp, runstore
from agentdescent.cli import NESTED_ENV

from tests.test_evolvespec import _dir_spec

#: The contract this file pins: the marker name alone is not enough, a host has
#: to be able to branch on the reason.  Spelled here, not imported, so the test
#: states the contract rather than agreeing with the implementation.
NESTED_REFUSAL = "nested-run"


def test_evolve_refuses_a_nested_run_before_creating_anything(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(NESTED_ENV, "1")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(_dir_spec(str(tmp_path / "tree")).to_dict()),
                    encoding="utf-8")

    def _no_create(*a, **k):
        raise AssertionError("a nested run must not be created")

    monkeypatch.setattr(runstore, "create", _no_create)
    # The subject is the nested guard, not the missing-CLI gate: satisfy that one
    # so a run that would otherwise start is refused for the nested reason only.
    monkeypatch.setattr(cli, "require_cli_on_path", lambda spec: None)

    code = cli.main(["--store", str(tmp_path / "runs"), "--json",
                     "evolve", str(spec)])

    reported = json.loads(capsys.readouterr().out)
    assert code == 2
    assert reported["ok"] is False
    assert reported["reason"] == NESTED_REFUSAL
    assert NESTED_ENV in reported["error"]
    assert not (tmp_path / "runs").exists()


def test_the_guard_answers_before_the_spec_is_read(tmp_path, monkeypatch, capsys):
    """Whatever the spec says, a worker's start request is refused, not parsed."""
    monkeypatch.setenv(NESTED_ENV, "1")
    code = cli.main(["--store", str(tmp_path / "runs"), "--json",
                     "evolve", str(tmp_path / "absent.json")])
    reported = json.loads(capsys.readouterr().out)
    assert code == 2
    assert reported["reason"] == NESTED_REFUSAL
    assert not (tmp_path / "runs").exists()


def test_the_guard_is_inactive_outside_a_worker(monkeypatch):
    monkeypatch.delenv(NESTED_ENV, raising=False)
    assert cli.nested_refusal() is None


def test_doctor_reports_the_nested_guard_and_its_reason(monkeypatch):
    monkeypatch.setenv(NESTED_ENV, "1")
    report = cli.doctor_report()
    assert report["nested"] is True
    assert report["nested_guard"] == NESTED_REFUSAL

    monkeypatch.delenv(NESTED_ENV)
    assert cli.doctor_report()["nested_guard"] is None


def test_the_mcp_start_stub_carries_the_same_named_reason(tmp_path, monkeypatch):
    monkeypatch.setenv(NESTED_ENV, "1")
    out = mcp.Tools(str(tmp_path / "runs")).start(
        _dir_spec(str(tmp_path / "tree")).to_dict())
    assert out["state"] == "refused" and out["nested"] is True
    assert out["reason"] == NESTED_REFUSAL
    assert NESTED_ENV in out["note"]
