"""An expired subscription is a config refusal, not a transient 400 (#1006).

Ark Coding answers an expired plan with HTTP 400 ``InvalidSubscription``.
Neither ``_provider_config_hint`` (401/403, 404, model/key markers) nor
``_quota_exhausted_hint`` (429/503) matched it, so it surfaced as a bare
``RuntimeError``: ``with_retries`` spent three attempts per call, the run died
45s later, ``diagnose`` recommended ``doctor`` (which only checks that the key
is set), and ``resume`` would relaunch into the same 400.

One call must stop the run, the error must name the subscription, ``diagnose``
must repeat that instead of the dead end, and ``resume`` must refuse without
``--force``. An ordinary 400 (context length) keeps the old behaviour.
"""

from __future__ import annotations

import io
import json
import os
import threading
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentdescent import ProviderConfigError, cli, diagnose_payload, runstore
from agentdescent.agents import anthropic_compatible, openai_compatible
from agentdescent.evolvespec import EvolveSpec

OK = {"choices": [{"message": {"content": "ok"}}],
      "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

#: Volcengine Ark Coding, an expired plan, on HTTP 400 as measured in #1006.
ARK_SUBSCRIPTION = {
    "error": {
        "code": "InvalidSubscription",
        "message": ("Your account (2100xxxx) does not have a valid CodingPlan "
                    "subscription, or your subscription has expired."),
    }
}
#: Anthropic bills an empty credit balance with a 400 too.
ANTHROPIC_BILLING = {
    "type": "error",
    "error": {"type": "billing_error",
              "message": "Your credit balance is too low to access the API."},
}
#: The guard: an ordinary 400 must keep failing as a plain RuntimeError.
CONTEXT_LENGTH = {
    "error": {"code": "context_length_exceeded",
              "message": "This model's maximum context length is 8192 tokens."}
}

SUBSCRIPTION_ERROR = (
    "SubscriptionInactive: https://ark.cn-beijing.volces.com/api/coding/v3 "
    "returned HTTP 400 for model 'deepseek-v4-flash': {\"error\":{\"code\":"
    "\"InvalidSubscription\",\"message\":\"Your account does not have a valid "
    "CodingPlan subscription, or your subscription has expired.\"}} -- the "
    "account has no active subscription for this endpoint: renew it at the "
    "provider, or point FAKE_KEY / model at another plan"
)


class _Handler(BaseHTTPRequestHandler):
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
    monkeypatch.setenv("FAKE_KEY", "sk-not-real")
    monkeypatch.setenv("FAKE_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")

    def use(*, code=400, body=None):
        _Handler.code = code
        _Handler.body = json.dumps(body if body is not None else {}).encode()
        _Handler.hits = 0

    yield use
    server.shutdown()
    server.server_close()


def _spec(retries=3, **evolve):
    model = {"ref": "openai_compatible", "model": "m", "api_key_env": "FAKE_KEY",
             "base_url_env": "FAKE_BASE_URL", "retries": retries}
    return EvolveSpec(
        kind="text", target="You are a helpful assistant.",
        data={"inline": [{"prompt": f"q{i}", "gold": "zzz"} for i in range(8)]},
        agent=model, reflect=dict(model),
        evolve={"rounds": 2, "n_workers": 4, "seed": 0, "patience": 10, **evolve})


def test_an_expired_subscription_fails_on_the_first_call(endpoint):
    from agentdescent.agents import SubscriptionInactive

    endpoint(body=ARK_SUBSCRIPTION)
    c = openai_compatible("m", api_key_env="FAKE_KEY", base_url_env="FAKE_BASE_URL",
                          retries=3)
    with pytest.raises(SubscriptionInactive) as info:
        c("hi")

    assert _Handler.hits == 1, "with_retries must not retry a subscription refusal"
    assert "no active subscription" in str(info.value)
    assert "FAKE_KEY" in str(info.value)
    assert "InvalidSubscription" in str(info.value)  # the provider's own words
    assert isinstance(info.value, ProviderConfigError)


def test_anthropic_billing_400_fails_fast_too(endpoint):
    from agentdescent.agents import SubscriptionInactive

    endpoint(body=ANTHROPIC_BILLING)
    c = anthropic_compatible("m", api_key_env="FAKE_KEY",
                             base_url_env="FAKE_BASE_URL", retries=3)
    with pytest.raises(SubscriptionInactive):
        c("hi")
    assert _Handler.hits == 1


def test_a_plain_400_is_still_retried_as_a_runtime_error(endpoint):
    endpoint(body=CONTEXT_LENGTH)
    c = openai_compatible("m", api_key_env="FAKE_KEY", base_url_env="FAKE_BASE_URL",
                          retries=3)
    with pytest.raises(RuntimeError) as info:
        c("hi")

    assert _Handler.hits == 3  # an ordinary 400 keeps its retries
    assert type(info.value).__name__ == "RuntimeError"
    assert "context_length_exceeded" in str(info.value)


def test_the_engine_stops_after_one_subscription_call(tmp_path, endpoint):
    endpoint(body=ARK_SUBSCRIPTION)
    store = str(tmp_path / "runs")
    rd = runstore.create(_spec().to_dict(), store=store)
    try:
        runstore.execute(rd)
    except Exception:  # noqa: BLE001 - status is what we assert on
        pass
    st = rd.status()

    assert st.state == "failed", st
    assert _Handler.hits <= 4, _Handler.hits  # one per in-flight worker, not 3 each
    assert "SubscriptionInactive" in (st.error or ""), st.error

    report = diagnose_payload(st.run_id, store=store)
    assert report.verdict == "run-failed"
    assert any("subscription" in r.lower() for r in report.recommendations)
    assert not any("doctor" in r for r in report.recommendations)


def test_resume_refuses_a_subscription_inactive_run(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runstore, "launch",
                        lambda rd, **kw: calls.append(rd.run_id)
                        or rd.update_status(state="running", pid=os.getpid()))
    store = str(tmp_path / "runs")
    rd = runstore.create({"kind": "text", "target": "hi"}, store=store)
    rd.update_status(state="failed", error=SUBSCRIPTION_ERROR, finished=1.0)

    err = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(err):
        code = cli.main(["--store", store, "resume", rd.run_id])

    text = err.getvalue()
    assert code == 2
    assert f"cannot resume {rd.run_id}" in text
    assert "SubscriptionInactive" in text
    assert "subscription" in text.lower()
    assert "--force" in text
    assert calls == []
