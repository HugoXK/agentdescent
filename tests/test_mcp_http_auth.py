"""`agentdescent mcp --transport streamable-http --http-token-env NAME` (#912).

The HTTP transport serves the whole tool set, including `apply` (writes files)
and `start` (spends model calls), so an unauthenticated peer is an unauthenticated
write-and-spend endpoint. The token comes from the environment only and the gate
sits in front of the ASGI app, which is what puts the 401 ahead of session
creation: no header means no `initialize`, no session id, no `tools/list`.

The names this file adds to `agentdescent.mcp` are looked up at call time so the
suite runs (and fails on the behaviour, not on an import) on a tree that does
not have them yet.
"""

import asyncio
import importlib
import json
import os
import socket
import subprocess
import sys
import time

import pytest

from agentdescent.cli import build_parser, main

TOKEN_ENV = "AGENTDESCENT_TEST_MCP_TOKEN"
TOKEN = "test-token-not-a-real-secret"


def _need(name):
    mod = importlib.import_module("agentdescent.mcp")
    obj = getattr(mod, name, None)
    assert obj is not None, f"agentdescent.mcp has no {name}"
    return obj


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve_cmd(port: int, *extra: str):
    return [sys.executable, "-m", "agentdescent", "mcp", "--transport",
            "streamable-http", "--port", str(port), *extra]


def _wait_until_listening(proc, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            if proc.poll() is not None or time.time() > deadline:
                raise AssertionError(proc.stderr.read().decode(errors="replace"))
            time.sleep(0.2)


def _stop(proc) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class _Resp:
    def __init__(self, status, headers, text):
        self.status_code, self.headers, self.text = status, headers, text


def _post(url, body, session=None, headers=None, _follow=True):
    import urllib.error
    import urllib.parse
    import urllib.request

    hdrs = {"Accept": "application/json, text/event-stream",
            "Content-Type": "application/json"}
    hdrs.update(headers or {})
    if session:
        hdrs["mcp-session-id"] = session
        hdrs["mcp-protocol-version"] = "2025-06-18"
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return _Resp(r.status, {k.lower(): v for k, v in r.headers.items()},
                         r.read().decode())
    except urllib.error.HTTPError as e:
        resp = _Resp(e.code, {k.lower(): v for k, v in e.headers.items()},
                     e.read().decode(errors="replace"))
        # mcp 1.8 mounts the handler at `/mcp` as a Starlette Mount, so `/mcp`
        # answers 307 to `/mcp/`; real clients follow that, and urllib does not
        # re-send a POST body, so follow it here.
        if _follow and e.code in (307, 308) and "location" in resp.headers:
            return _post(urllib.parse.urljoin(url, resp.headers["location"]), body,
                         session=session, headers=headers, _follow=False)
        return resp


def _initialize() -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}}}


def _rpc_result(resp):
    text = resp.text
    if "text/event-stream" in resp.headers.get("content-type", ""):
        data = [line[5:].strip() for line in text.splitlines()
                if line.startswith("data:")]
        text = data[-1]
    return json.loads(text)["result"]


# --- the flag and the environment -------------------------------------------


def test_token_env_flag_is_opt_in_and_named_after_a_variable():
    a = build_parser().parse_args(["mcp"])
    assert a.http_token_env is None          # no gate unless asked for
    a = build_parser().parse_args(["mcp", "--http-token-env", "MY_TOKEN"])
    assert a.http_token_env == "MY_TOKEN"


def test_an_unset_or_empty_variable_refuses_to_start_instead_of_disabling_the_gate(monkeypatch):
    http_token = _need("http_token")
    missing = _need("HttpTokenMissing")
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    with pytest.raises(missing, match="not set"):
        http_token(TOKEN_ENV)
    monkeypatch.setenv(TOKEN_ENV, "   ")
    with pytest.raises(missing, match="not set"):
        http_token(TOKEN_ENV)
    assert http_token(None) is None


def test_loopback_http_without_the_flag_keeps_serving(monkeypatch, capsys):
    # Control: the gate is opt-in, so an existing loopback setup is unchanged.
    import agentdescent.mcp as m

    seen = {}

    def fake_serve(**kw):
        seen.update(kw)

    monkeypatch.setattr(m, "serve", fake_serve)
    assert main(["mcp", "--transport", "streamable-http",
                 "--port", str(_free_port())]) == 0
    err = capsys.readouterr().err
    assert "bearer token required" not in err
    assert seen.get("http_token_env") is None   # nothing to gate, nothing asked


# --- --allow-remote needs the token -----------------------------------------


def test_allow_remote_without_a_token_env_is_refused(capsys):
    rc = main(["mcp", "--transport", "streamable-http", "--host", "0.0.0.0",
               "--allow-remote", "--port", "9"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--http-token-env" in err and "0.0.0.0" in err
    assert "streamable-http on" not in err


def test_an_empty_variable_fails_before_the_url_is_announced(monkeypatch, capsys):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    rc = main(["mcp", "--transport", "streamable-http", "--port", "9",
               "--http-token-env", TOKEN_ENV])
    assert rc == 2
    err = capsys.readouterr().err
    assert TOKEN_ENV in err and "streamable-http on" not in err
    # The variable's name may appear; a value never does (there is none here).
    assert TOKEN not in err


def test_stdio_rejects_a_token_env(capsys):
    # stdio carries no HTTP headers, so accepting the flag would be a silent no-op.
    rc = main(["mcp", "--http-token-env", TOKEN_ENV])
    assert rc == 2
    assert "--http-token-env" in capsys.readouterr().err


# --- the gate itself --------------------------------------------------------


def _asgi_call(app, scope, headers=b""):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = dict(scope)
    scope.setdefault("type", "http")
    scope["headers"] = list(headers) if headers else []
    asyncio.run(app(scope, receive, send))
    return sent


def _inner(calls):
    async def app(scope, receive, send):
        calls.append(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return app


def test_a_request_without_the_bearer_header_never_reaches_the_mcp_layer():
    guard = _need("_bearer_guard")
    calls = []
    sent = _asgi_call(guard(_inner(calls), TOKEN), {"path": "/mcp"})
    assert sent[0]["status"] == 401 and calls == []
    assert dict(sent[0]["headers"])[b"www-authenticate"].startswith(b"Bearer")
    wrong = [(b"authorization", b"Bearer nope")]
    sent = _asgi_call(guard(_inner(calls), TOKEN), {"path": "/mcp"}, wrong)
    assert sent[0]["status"] == 401 and calls == []
    right = [(b"authorization", ("Bearer " + TOKEN).encode())]
    sent = _asgi_call(guard(_inner(calls), TOKEN), {"path": "/mcp"}, right)
    assert sent[0]["status"] == 200 and len(calls) == 1


def test_lifespan_scopes_pass_through_so_the_session_manager_starts():
    guard = _need("_bearer_guard")
    calls = []
    _asgi_call(guard(_inner(calls), TOKEN), {"type": "lifespan"})
    assert len(calls) == 1


# --- end to end: the 401 is ahead of session init ---------------------------


def _start_token_server(tmp_path, port, token=TOKEN):
    # The child cannot rely on the parent's relative PYTHONPATH (its cwd is the
    # tmp dir), so the checkout root is passed absolutely.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, AGENTDESCENT_HOME=str(tmp_path), **{TOKEN_ENV: token})
    env["PYTHONPATH"] = root + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.Popen(
        _serve_cmd(port, "--http-token-env", TOKEN_ENV),
        cwd=str(tmp_path), env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE)
    _wait_until_listening(proc, port)
    return proc


def test_the_first_initialize_post_without_the_header_is_401_not_a_session(tmp_path):
    pytest.importorskip("mcp")
    port = _free_port()
    proc = _start_token_server(tmp_path, port)
    try:
        resp = _post(f"http://127.0.0.1:{port}/mcp", _initialize())
        assert resp.status_code == 401, resp.text
        assert "mcp-session-id" not in resp.headers
        assert "serverInfo" not in resp.text
    finally:
        _stop(proc)


def test_the_same_initialize_with_the_header_reaches_the_mcp_layer(tmp_path):
    pytest.importorskip("mcp")
    port = _free_port()
    proc = _start_token_server(tmp_path, port)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        resp = _post(url, _initialize(),
                     headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200, resp.text
        assert _rpc_result(resp)["serverInfo"]["name"] == "agentdescent"
        assert resp.headers.get("mcp-session-id")
    finally:
        _stop(proc)
