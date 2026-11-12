"""Agent and grader pipes are UTF-8, independent of the parent's locale (#973)."""

import os
import subprocess
import sys

import pytest

from agentdescent.agents import AgentError, Usage, cli_agent
from agentdescent.evolution import Task
from agentdescent.rewards import GraderError, command_scorer, exact_match
from agentdescent.runners import _sh


TEXT = "\u4f60\u597d \U0001f680"


@pytest.fixture(autouse=True)
def legacy_parent_encoding(monkeypatch):
    """Simulate a non-UTF-8 text default without requiring an installed locale.

    The children are real processes and speak UTF-8 bytes. Only an unspecified
    parent-side text encoding changes, on Windows as well as POSIX.
    """
    popen = subprocess.Popen

    def legacy_popen(*args, **kwargs):
        if (kwargs.get("text") or kwargs.get("universal_newlines")) and not kwargs.get("encoding"):
            kwargs["encoding"] = "cp1252"
        return popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", legacy_popen)


def command(source):
    return [sys.executable, "-B", "-c", source]


@pytest.mark.parametrize("via_stdin", [False, True])
def test_cli_roundtrips_unicode_without_changing_the_reward(via_stdin):
    source = (
        "import sys; "
        + ("text=sys.stdin.buffer.read().decode('utf-8'); " if via_stdin else "text=sys.argv[-1]; ")
        + "sys.stdout.buffer.write(text.encode('utf-8'))"
    )
    usage = Usage()
    result = cli_agent(command(source), via_stdin=via_stdin, usage=usage)(TEXT)
    assert result == TEXT
    assert exact_match()(Task("t", "q", {"gold": TEXT}), result) == 1.0
    assert usage.calls == 1 and usage.failures == 0


def test_cli_error_preserves_utf8_diagnostic():
    source = f"import sys; sys.stderr.buffer.write({ascii(TEXT)}.encode('utf-8')); sys.exit(2)"
    usage = Usage()
    with pytest.raises(AgentError) as caught:
        cli_agent(command(source), usage=usage)("q")
    assert TEXT in str(caught.value)
    assert usage.calls == 1 and usage.failures == 1


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_cli_invalid_utf8_is_a_counted_agent_error(stream):
    usage = Usage()
    source = f"import sys; sys.{stream}.buffer.write(b'\\xff')"
    with pytest.raises(AgentError, match="UTF-8"):
        cli_agent(command(source), usage=usage)("q")
    assert usage.calls == 1 and usage.failures == 1


def test_command_scorer_exchanges_utf8_json_and_diagnostics():
    source = (
        "import json, os, sys; "
        "p=json.loads(sys.stdin.buffer.read().decode('utf-8')); "
        f"expected={ascii(TEXT)}; "
        "assert p == {'id': expected, 'prompt': expected, 'meta': {'gold': expected}, 'output': expected}; "
        "assert os.environ['ANSWER'] == expected; "
        "sys.stderr.buffer.write(expected.encode('utf-8')); "
        "sys.stdout.buffer.write((expected + '\\n1').encode('utf-8'))"
    )
    assert command_scorer(command(source))(Task(TEXT, TEXT, {"gold": TEXT}), TEXT) == 1.0


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_command_scorer_invalid_utf8_is_a_grader_error(stream):
    source = f"import sys; sys.stdout.buffer.write(b'1\\n'); sys.{stream}.buffer.write(b'\\xff')"
    with pytest.raises(GraderError, match="UTF-8"):
        command_scorer(command(source))(Task("t", "q"), "a")


def test_runner_decodes_both_pipes_and_preserves_newline_normalization(tmp_path):
    source = (
        f"import sys; text={ascii(TEXT)}; "
        "sys.stdout.buffer.write((text + '\\r\\nx\\ry').encode('utf-8')); "
        "sys.stderr.buffer.write(text.encode('utf-8'))"
    )
    proc = _sh(command(source), str(tmp_path), 20, dict(os.environ))
    assert proc.returncode == 0
    assert proc.stdout == TEXT + "\nx\ny"
    assert proc.stderr == TEXT


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_runner_invalid_utf8_is_an_agent_error(tmp_path, stream):
    source = f"import sys; sys.{stream}.buffer.write(b'\\xff')"
    with pytest.raises(AgentError, match="UTF-8"):
        _sh(command(source), str(tmp_path), 20, dict(os.environ))
