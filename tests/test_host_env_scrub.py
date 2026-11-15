"""A detached run does not inherit the host session's identity or MCP config (#1082).

The worker's own gates run under an allowlist (:func:`runners._child_env`), but
the run `launch` detaches is our process, so it needs the API keys and PATH the
allowlist would drop. The cure is a denylist -- ``SESSION_MARKERS``, the same
tuple the candidate worker drops -- so `DSH_*`, `CLAUDE*`, `CODEX*`, `MCP_*`,
the OpenCode config carriers and `XDG_CONFIG_HOME` stay with the host, and
everything else, including the credentials the run needs, is passed through.

The parametrised row is the one that cannot go stale: it walks the tuple itself,
so a marker added for a new host is covered here the day it is added.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
from unittest import mock

import pytest

from agentdescent import integrations, runstore
from agentdescent.agents import SESSION_MARKERS as AGENTS_SESSION_MARKERS
from agentdescent.surface_common import DETACHED_KEEP_VARS, SESSION_MARKERS, scrub_host_env

HOST_MARKERS = {
    "DSH_SESSION_ID": "host-session",
    "DSH_WORKSPACE": "/host/workspace",
    "CLAUDE_CODE_ENTRYPOINT": "cli",
    "CLAUDECODE": "1",
    "CODEX_SANDBOX": "1",
    "MCP_SERVERS": '{"filesystem": {}}',
}

#: The host config/home directories the run itself reads
#: (``integrations._host_root``), so a worker spec with ``isolate: false`` -- and
#: every ``agentdescent start`` from a plain terminal -- resolves the user's real
#: setup instead of the default home (#1082 review). The fourth is
#: ``XDG_CONFIG_HOME``: OpenCode resolves its config under XDG, which is the
#: variable that actually moves it.
HOST_CONFIG_DIRS = {
    "CLAUDE_CONFIG_DIR": "/home/someone/.claude-work",
    "CODEX_HOME": "/home/someone/.codex-work",
    "DSH_HOME": "/home/someone/.dsh-work",
    "XDG_CONFIG_HOME": "/home/someone/.config-work",
}

#: One variable per marker, spelled the way a host would set it: the bare name
#: when the marker ends in ``_`` (``CLAUDECODE``), a suffixed one otherwise.
def _host_variable(marker: str) -> str:
    return marker if marker.endswith("_") else marker + "_PROBE"


def test_scrub_drops_host_markers_and_keeps_what_the_run_needs(monkeypatch):
    for name, value in HOST_MARKERS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ARK_API_KEY", "not-a-real-key")

    env = scrub_host_env(os.environ)

    for name in HOST_MARKERS:
        assert name not in env
    assert env["ARK_API_KEY"] == "not-a-real-key"
    assert env["PATH"] == os.environ["PATH"]


def _host_root_variables() -> set:
    """The names ``integrations._host_root`` is actually called with.

    Read from the module's own source, so a fifth host root added there fails the
    drift row below instead of silently resolving to its default directory.
    """
    tree = ast.parse(inspect.getsource(integrations))
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_host_root" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            names.add(node.args[0].value)
    return names


def test_the_keep_set_covers_every_variable_host_root_reads():
    """The keep list is in the leaf module, so a test binds it to `integrations`.

    Both directions: a fifth host root fails the first assert, and a name the
    worker's own map does not know fails the second -- so neither list can move
    alone.
    """
    from agentdescent.agents import WORKER_CONFIG_DIRS

    roots = _host_root_variables()
    assert roots == {"DSH_HOME", "CODEX_HOME", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR"}
    assert roots <= set(DETACHED_KEEP_VARS)
    assert set(DETACHED_KEEP_VARS) <= set(WORKER_CONFIG_DIRS)


def test_every_host_root_resolves_under_the_scrubbed_environment(monkeypatch):
    """After the scrub each host still finds the directory it was configured with."""
    for name, value in HOST_CONFIG_DIRS.items():
        monkeypatch.setenv(name, value)

    env = scrub_host_env(os.environ)

    with mock.patch.dict(os.environ, env, clear=True):
        assert integrations._dsh_root("/home/someone", True) == HOST_CONFIG_DIRS["DSH_HOME"]
        assert integrations._codex_root("/home/someone", True) == HOST_CONFIG_DIRS["CODEX_HOME"]
        assert (integrations._claude_root("/home/someone", True)
                == HOST_CONFIG_DIRS["CLAUDE_CONFIG_DIR"])
        assert (integrations._opencode_root("/home/someone", True)
                == os.path.join(HOST_CONFIG_DIRS["XDG_CONFIG_HOME"], "opencode"))


def test_an_isolated_worker_still_loses_and_redirects_the_config_dirs(tmp_path, monkeypatch):
    """The keep set is the detached run's; a candidate worker keeps none of it.

    Asserted as where each value points, not merely as absence: an absence-only
    row would pass while the worker still pointed at the host's directory if the
    redirect ever stopped taking (#1082 review).
    """
    from agentdescent.agents import worker_env

    for name, value in HOST_CONFIG_DIRS.items():
        monkeypatch.setenv(name, value)

    env = worker_env(str(tmp_path), isolate=True)
    expected = {
        "CLAUDE_CONFIG_DIR": "claude",
        "CODEX_HOME": "codex",
        "DSH_HOME": "dsh",
        "XDG_CONFIG_HOME": "xdg",
    }

    for name, leaf in expected.items():
        assert env[name] == os.path.join(str(tmp_path), ".agentdescent-worker", leaf), name

    # `isolate=False` is the opposite contract: the worker sees the user's setup,
    # which is why the detached run keeps these four in the first place.
    loose = worker_env(str(tmp_path), isolate=False)
    for name, value in HOST_CONFIG_DIRS.items():
        assert loose[name] == value, name


def test_the_host_config_dirs_survive_and_the_session_does_not(monkeypatch):
    """The row the review named: the host's config/home dirs survive `launch`.

    `CLAUDE_CONFIG_DIR`, `CODEX_HOME` and `DSH_HOME` are host *configuration*,
    which this package reads through `integrations._host_root`, not session
    identity: dropping them sent a worker spec with `isolate: false` -- and every
    `agentdescent start` from a terminal -- to `~/.claude` / `~/.codex`, which for
    a custom directory is the wrong, often unauthenticated, login (#1082 review).
    """
    for name, value in HOST_CONFIG_DIRS.items():
        monkeypatch.setenv(name, value)
    for name, value in HOST_MARKERS.items():
        monkeypatch.setenv(name, value)

    env = scrub_host_env(os.environ)

    for name, value in HOST_CONFIG_DIRS.items():
        assert env[name] == value, name
    for name in HOST_MARKERS:
        assert name not in env, name


def test_launch_keeps_the_host_config_dirs_and_drops_the_session(tmp_path, monkeypatch):
    for name, value in HOST_CONFIG_DIRS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("DSH_SESSION_ID", "host-session")
    monkeypatch.setenv("MCP_SERVERS", '{"filesystem": {}}')
    rd = runstore.create({"kind": "text", "target": str(tmp_path / "out.md")},
                         store=str(tmp_path / "store"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, stdout="4242\n", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)

    st = runstore.launch(rd)

    assert st.pid == 4242
    env = seen["env"]
    for name, value in HOST_CONFIG_DIRS.items():
        assert env[name] == value, name
    assert "CLAUDECODE" not in env
    assert "DSH_SESSION_ID" not in env
    assert "MCP_SERVERS" not in env


def test_scrub_does_not_mutate_the_caller(monkeypatch):
    monkeypatch.setenv("DSH_SESSION_ID", "host-session")

    env = scrub_host_env(os.environ)

    assert env is not os.environ
    assert os.environ["DSH_SESSION_ID"] == "host-session"


def test_launch_hands_the_child_a_scrubbed_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_SESSION_ID", "host-session")
    monkeypatch.setenv("MCP_SERVERS", '{"filesystem": {}}')
    monkeypatch.setenv("ARK_API_KEY", "not-a-real-key")
    rd = runstore.create({"kind": "text", "target": str(tmp_path / "out.md")},
                         store=str(tmp_path / "store"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, stdout="4242\n", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)

    st = runstore.launch(rd)

    assert st.pid == 4242
    env = seen["env"]
    assert "DSH_SESSION_ID" not in env and "MCP_SERVERS" not in env
    assert env["ARK_API_KEY"] == "not-a-real-key"
    assert env["PYTHONPATH"]  # the launcher still makes the package importable


@pytest.mark.parametrize("marker", SESSION_MARKERS)
def test_every_session_marker_is_dropped(marker):
    """A marker added for a new host is covered without a second list (#1082).

    The scrub used to carry its own four prefixes, so five of these eleven
    crossed it; this row walks the tuple instead of naming them.
    """
    env = scrub_host_env({_host_variable(marker): "host-session", "PATH": "/bin"})

    assert [name for name in env if name != "PATH"] == []
    assert env["PATH"] == "/bin"


def test_the_worker_and_the_detached_run_share_one_list():
    """The two consumers of the denylist cannot drift apart again (#1082)."""
    assert AGENTS_SESSION_MARKERS is SESSION_MARKERS


def test_a_provider_key_that_merely_looks_like_a_marker_is_kept():
    """``OPENCODE_API_KEY`` is a credential, not a config pointer (#1082)."""
    env = scrub_host_env({"OPENCODE_API_KEY": "not-a-real-key", "OPENCODE_CONFIG": "/x"})

    assert env == {"OPENCODE_API_KEY": "not-a-real-key"}


def test_launch_re_scrubs_a_caller_supplied_env(tmp_path, monkeypatch):
    """A caller cannot put the host session back through ``env=`` (#1082)."""
    rd = runstore.create({"kind": "text", "target": str(tmp_path / "out.md")},
                         store=str(tmp_path / "store"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, stdout="4242\n", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)

    runstore.launch(rd, env={"MCP_SERVERS": '{"filesystem": {}}',
                             "DSH_SESSION_ID": "host-session",
                             "RUN_TAG": "kept"})

    env = seen["env"]
    assert "MCP_SERVERS" not in env and "DSH_SESSION_ID" not in env
    assert env["RUN_TAG"] == "kept"
    assert env["PYTHONPATH"]
