"""`plan --probe` answers "can this run start" before a run store entry exists (#1048).

Measured: with the key set and the plan expired, `doctor` said `no blocking
problems`, `algorithms run` / `plan` were all green, and the first real answer
came from `evolve` -- as `SubscriptionInactive` plus a `failed round 0/1` entry
in the run store. For `evolve --detach` and a host's Path A `start` that means
waiting for `status` to learn it could never have started.

The flag is opt-in, so the promise that plain `plan` runs nothing (and sends
nothing) is pinned here too.
"""
from __future__ import annotations

import io
import json
import os
import threading
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentdescent import cli

OK = {"choices": [{"message": {"content": "ok"}}],
      "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

#: Volcengine Ark Coding, an expired plan, on HTTP 400 as measured in #1006.
ARK_SUBSCRIPTION = {
    "error": {
        "code": "InvalidSubscription",
        "message": ("Your account does not have a valid CodingPlan subscription, "
                    "or your subscription has expired."),
    }
}
#: An endpoint that answers but does not serve the model named.
UNSUPPORTED_MODEL = {
    "error": {"code": "UnsupportedModel",
              "message": "The model `m` does not exist."},
}


class _Handler(BaseHTTPRequestHandler):
    url: str = ""
    body: bytes = b"{}"
    code: int = 400
    hits = 0
    lock = threading.Lock()

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with type(self).lock:
            type(self).hits += 1
        payload = (json.dumps(OK).encode() if type(self).code == 200
                   else type(self).body)
        self.send_response(type(self).code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # noqa: D401
        pass


@pytest.fixture
def endpoint(monkeypatch):
    _Handler.hits = 0
    _Handler.code = 400
    _Handler.body = b"{}"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Handler.url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("FAKE_KEY", "sk-not-real")
    monkeypatch.setenv("FAKE_BASE_URL", _Handler.url)

    def use(*, code=400, body=None):
        _Handler.code = code
        _Handler.body = json.dumps(body if body is not None else {}).encode()
        _Handler.hits = 0

    yield use
    server.shutdown()
    server.server_close()


def _write_spec(tmp_path, *, agent=None, reflect=None):
    model = {"ref": "openai_compatible", "model": "m", "api_key_env": "FAKE_KEY",
             "base_url_env": "FAKE_BASE_URL", "retries": 1}
    spec = {
        "version": 1,
        "kind": "text",
        "target": "You are a helpful assistant.",
        "data": {"inline": [{"prompt": f"q{i}", "gold": "zzz"} for i in range(8)]},
        "agent": agent or dict(model),
        "reflect": reflect or dict(model),
        "evolve": {"rounds": 1, "n_workers": 1, "seed": 0},
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


def _store_is_empty(store):
    return not os.path.exists(store) or not os.listdir(store)


def test_an_expired_subscription_fails_the_plan_before_a_run(tmp_path, endpoint):
    endpoint(body=ARK_SUBSCRIPTION)
    store = str(tmp_path / "runs")

    code, out, err = _run(["--store", store, "plan", _write_spec(tmp_path), "--probe"])

    text = out + err
    assert code == 1
    assert "SubscriptionInactive" in text
    # The next step travels with it, so the reader is not sent to `doctor`.
    assert "no active subscription" in text
    assert "renew the subscription" in text
    # One call, and no run store entry: the whole point of the flag.
    assert _Handler.hits == 1
    assert _store_is_empty(store)
    # `next:` stays last, but it is the repair action, not evolve (#1093).
    last = out.strip().splitlines()[-1]
    assert last.startswith("next: renew the subscription")
    assert "next: agentdescent evolve " not in out
    assert f"then: agentdescent plan {tmp_path / 'spec.json'} --probe" in out


def test_a_runnable_endpoint_reports_ok_and_exits_zero(tmp_path, endpoint):
    endpoint(code=200)

    code, out, err = _run(["plan", _write_spec(tmp_path), "--probe"])

    assert code == 0, (out, err)
    assert "probe: agent ok (m," in out
    assert "probe: reflect" not in out, "an identical reflector must not spend a second call"
    assert _Handler.hits == 1


def test_without_the_flag_plan_sends_nothing(tmp_path, endpoint):
    endpoint(code=200)

    code, out, err = _run(["plan", _write_spec(tmp_path)])

    assert code == 0, (out, err)
    assert _Handler.hits == 0, "plain plan must stay free"
    assert "probe:" not in out + err


def test_an_unsupported_model_names_the_model(tmp_path, endpoint):
    endpoint(code=404, body=UNSUPPORTED_MODEL)

    code, out, err = _run(["plan", _write_spec(tmp_path), "--probe"])

    text = out + err
    assert code == 1
    assert "does not serve model 'm'" in text
    assert "check `model`" in text


def test_the_flag_keeps_a_host_model_out_of_the_probe(tmp_path, endpoint):
    endpoint(code=200)
    spec = _write_spec(tmp_path, agent={"ref": "host_model"}, reflect={"ref": "host_model"})

    code, out, err = _run(["plan", spec, "--probe"])

    assert code == 0, (out, err)
    assert "probe: agent skipped" in out
    assert _Handler.hits == 0


def test_the_json_form_carries_the_probe_only_when_asked(tmp_path, endpoint):
    endpoint(code=200)
    spec = _write_spec(tmp_path)

    plain_code, plain_out, _ = _run(["plan", spec, "--json"])
    assert plain_code == 0
    assert "probe" not in json.loads(plain_out)

    code, out, _ = _run(["plan", spec, "--json", "--probe"])
    payload = json.loads(out)
    assert code == 0
    rows = payload["probe"]["rows"]
    assert [row["state"] for row in rows] == ["ok"]
    assert rows[0]["field"] == "agent"


def test_the_probe_asks_the_same_model_the_run_would(tmp_path, monkeypatch, endpoint):
    """A probe that swaps the model (or drops it) answers a different question."""
    import agentdescent.probe as probe_module

    seen = {}

    def fake_claude(**kwargs):
        seen.update(kwargs)
        return lambda prompt: "ok"

    monkeypatch.setitem(probe_module._MODEL_ADAPTERS, "claude", fake_claude)
    endpoint(code=200)
    spec = _write_spec(tmp_path, agent={"ref": "claude", "model": "claude-x",
                                        "api_key_env": "FAKE_KEY", "max_tokens": 8},
                       reflect={"ref": "echo"})

    code, out, err = _run(["plan", spec, "--probe"])

    assert code == 0, (out, err)
    assert seen["model"] == "claude-x", seen
    assert "api_key_env" not in seen or seen["api_key_env"] == "FAKE_KEY"
    assert "stream" not in seen and "default_base_url" not in seen


def _cases(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps({"prompt": f"q{i}", "gold": "zzz"})
                               for i in range(8)), encoding="utf-8")
    return str(path)


def _prompt(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("You are a helpful assistant.", encoding="utf-8")
    return str(path)


def _algorithms_run_args(tmp_path, *, extra=(), base_url="http://127.0.0.1:1"):
    return ["algorithms", "run", "gepa", _prompt(tmp_path), _cases(tmp_path),
            "--agent", "openai_compatible", "--model", "m",
            "--key-env", "FAKE_KEY", "--base-url", base_url,
            "--rounds", "1", "--workers", "1",
            "--out", str(tmp_path / "algo.spec.json"), *extra]


def test_algorithms_run_json_exits_nonzero_on_a_refused_probe(tmp_path, monkeypatch,
                                                              endpoint):
    """A host gates on this exit code before it starts the run (#1048 review)."""
    endpoint(body=ARK_SUBSCRIPTION)

    code, out, err = _run(_algorithms_run_args(
        tmp_path, extra=["--json", "--probe"], base_url=_Handler.url))

    payload = json.loads(out)
    assert payload["probe"]["ok"] is False
    assert payload["ok"] is True, "the plan itself is fine; only the probe refused"
    assert payload["ready"] is False
    assert payload["next"] == (
        "renew the subscription at the provider, or point api_key_env / "
        "model at another plan")
    assert "evolve" not in payload["next"]
    assert code == 1, (code, err)


def test_algorithms_run_human_form_exits_nonzero_too(tmp_path, monkeypatch, endpoint):
    endpoint(body=ARK_SUBSCRIPTION)

    code, out, err = _run(_algorithms_run_args(
        tmp_path, extra=["--probe"], base_url=_Handler.url))

    assert code == 1, (code, out, err)
    assert "probe: agent failed" in out + err
    last = out.strip().splitlines()[-1]
    assert last.startswith("next: renew the subscription")
    assert "next: agentdescent evolve" not in out


def test_the_probe_caps_the_reply_budget_and_the_wait(tmp_path, monkeypatch, endpoint):
    """One word is bought, not 4096 tokens (#1048 review)."""
    import agentdescent.probe as probe_module

    seen = {}

    def fake_claude(**kwargs):
        seen.update(kwargs)
        return lambda prompt: "ok"

    monkeypatch.setitem(probe_module._MODEL_ADAPTERS, "claude", fake_claude)
    endpoint(code=200)
    spec = _write_spec(tmp_path, agent={"ref": "claude", "model": "claude-x"},
                       reflect={"ref": "echo"})

    code, out, err = _run(["plan", spec, "--probe"])

    assert code == 0, (out, err)
    assert seen["max_tokens"] == probe_module.PROBE_MAX_TOKENS
    assert seen["timeout"] == probe_module.DEFAULT_PROBE_TIMEOUT

def test_plan_json_marks_a_refused_probe_unready_and_keeps_ok(tmp_path, endpoint):
    """`ok` stays about the plan; `ready` and `next` are how a host gates (#1093)."""
    endpoint(body=ARK_SUBSCRIPTION)

    code, out, err = _run(["plan", _write_spec(tmp_path), "--json", "--probe"])

    payload = json.loads(out)
    assert code == 1, (code, err)
    assert payload["ok"] is True
    assert payload["ready"] is False
    assert payload["probe"]["ok"] is False
    assert payload["next"] == (
        "renew the subscription at the provider, or point api_key_env / "
        "model at another plan")


def test_a_successful_probe_still_recommends_evolve(tmp_path, endpoint):
    endpoint(code=200)
    spec = _write_spec(tmp_path)

    code, out, err = _run(["plan", spec, "--probe"])
    assert code == 0, (out, err)
    assert out.strip().splitlines()[-1].startswith("next: agentdescent evolve ")
    assert "then: " not in out

    json_code, json_out, json_err = _run(["plan", spec, "--json", "--probe"])
    payload = json.loads(json_out)
    assert json_code == 0, (json_out, json_err)
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert payload["probe"]["ok"] is True
    assert "next" not in payload


def test_without_the_flag_json_has_no_ready_field(tmp_path, endpoint):
    endpoint(code=200)

    code, out, err = _run(["plan", _write_spec(tmp_path), "--json"])

    assert code == 0, (out, err)
    payload = json.loads(out)
    assert "probe" not in payload
    assert "ready" not in payload
    assert "next" not in payload
