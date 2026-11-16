"""The one-call preflight behind ``plan --probe`` (#1048).

``plan`` proves the spec's *shape* and ``doctor`` proves a key is *present*;
neither can say whether the key, endpoint, model and subscription actually
work together. The first call used to happen inside ``evolve``, after a run
store entry existed -- and for ``evolve --detach`` or a host's Path A ``start``
that meant waiting for ``status`` to learn the plan had expired.

This module sends exactly one minimal completion per model-backed agent and
reflector, through the same adapter the run would use, so the refusal is the
same class (``SubscriptionInactive`` / ``QuotaExhausted`` /
``ProviderConfigError``) and the same hint. It never starts a run, never writes
a run store entry, and never calls a CLI agent -- those cost a whole session,
so they report ``skipped``.
"""
from __future__ import annotations

import time
from functools import partial
from typing import Any, Callable, Dict, Mapping, Optional

from .agents import (Completion, ProviderConfigError, QuotaExhausted,
                     SubscriptionInactive, claude, openai_compatible)

#: A cheap, unambiguous turn. One short reply, no reasoning budget needed.
PROBE_PROMPT = "Reply with the single word ok."

#: Adapters that answer over the wire, by the refs a spec may use.
_MODEL_ADAPTERS: Dict[str, Callable[..., Completion]] = {
    "openai_compatible": openai_compatible,
    "agentdescent.agents:openai_compatible": openai_compatible,
    "claude": claude,
    "agentdescent.agents:claude": claude,
}

#: Refs that would spend an agent session or need the host that started the run.
_SKIPPED_REFS = {
    "claude_code": "cli agent",
    "codex": "cli agent",
    "dsh": "cli agent",
    "opencode": "cli agent",
    "cli_agent": "cli agent",
    "host_model": "the model of the host that started the run",
}

#: ``claude`` speaks the Anthropic SDK, which has no endpoint/stream knobs.
_CLAUDE_REFS = {"claude", "agentdescent.agents:claude"}
_NOT_FOR_CLAUDE = {"base_url_env", "default_base_url", "stream"}

#: A dead endpoint must not hold ``plan`` for the adapter's full run timeout.
DEFAULT_PROBE_TIMEOUT = 20.0

#: One word is all the probe asks for; the adapter default (4096) buys nothing
#: and a reasoning model can spend it on hidden thinking (#1048 review).
PROBE_MAX_TOKENS = 16


def _block(spec: Any, field: str) -> Optional[Dict[str, Any]]:
    """The spec's agent block as a dict; a bare string ref becomes ``{"ref": …}``."""
    value = getattr(spec, field, None)
    if isinstance(value, str) and value:
        return {"ref": value}
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _next_step(error: BaseException) -> str:
    """The sentence a reader can act on, matching the class of refusal (#1006)."""
    if isinstance(error, SubscriptionInactive):
        return ("renew the subscription at the provider, or point api_key_env / "
                "model at another plan")
    if isinstance(error, QuotaExhausted):
        return ("wait for the reset the provider names, or point api_key_env / "
                "model at another plan")
    if isinstance(error, ProviderConfigError):
        return ("fix the hint in the error (model name, base URL, or API key "
                "variable) and re-run plan --probe")
    return "run `agentdescent doctor`, then re-run plan --probe"


def _completion(ref: str, block: Mapping[str, Any]) -> Completion:
    """The adapter this spec would run, built exactly as the engine builds it."""
    adapter = _MODEL_ADAPTERS[ref]
    kwargs = {k: v for k, v in block.items() if k != "ref"}
    if ref in _CLAUDE_REFS:
        # `claude(model=…)` takes the model as a keyword, so it stays in kwargs:
        # probing a different model than the run would use answers nothing.
        kwargs = {k: v for k, v in kwargs.items() if k not in _NOT_FOR_CLAUDE}
        build = adapter
    else:
        model = kwargs.pop("model", None)
        if not isinstance(model, str) or not model:
            raise ValueError("the spec names no model for this agent")
        build = partial(adapter, model)
    # A probe is a preflight, not the run: cap the wait and the reply budget,
    # keeping a caller's own smaller number when it set one.
    timeout = kwargs.get("timeout")
    kwargs["timeout"] = min(float(timeout), DEFAULT_PROBE_TIMEOUT) \
        if isinstance(timeout, (int, float)) and timeout > 0 else DEFAULT_PROBE_TIMEOUT
    tokens = kwargs.get("max_tokens")
    kwargs["max_tokens"] = min(int(tokens), PROBE_MAX_TOKENS) \
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0 \
        else PROBE_MAX_TOKENS
    return build(**kwargs)


def _one(field: str, block: Mapping[str, Any]) -> Dict[str, Any]:
    ref = block.get("ref")
    row: Dict[str, Any] = {"field": field, "ref": ref}
    if not isinstance(ref, str) or not ref:
        row.update(state="skipped", detail="the spec names no agent")
        return row
    row["model"] = block.get("model")
    if ref in _SKIPPED_REFS:
        row.update(state="skipped", detail=_SKIPPED_REFS[ref])
        return row
    if ref not in _MODEL_ADAPTERS:
        row.update(state="skipped", detail=f"no probe for ref {ref!r}")
        return row
    started = time.monotonic()
    try:
        completion = _completion(ref, block)
        completion(PROBE_PROMPT)
    except Exception as error:  # noqa: BLE001 - every refusal is the report
        row.update(state="failed", seconds=round(time.monotonic() - started, 2),
                   detail=f"{type(error).__name__}: {error}",
                   next=_next_step(error))
        return row
    row.update(state="ok", seconds=round(time.monotonic() - started, 2))
    return row


def probe_payload(spec: Any) -> Dict[str, Any]:
    """One minimal call per model-backed agent and reflector (#1048).

    ``ok`` is false only for a real refusal: a skipped ref (a CLI agent, the
    host's model) is reported and does not fail the plan, because there is
    nothing here for the probe to answer for it.
    """
    rows = []
    # The reflector defaults to the agent when the spec names none, so probing it
    # again would spend the same call twice and report the same refusal twice.
    seen = set()
    for field in ("agent", "reflect"):
        block = _block(spec, field)
        if block is None:
            continue
        key = (block.get("ref"), block.get("model"))
        if field == "reflect" and key in seen:
            continue
        seen.add(key)
        rows.append(_one(field, block))
    return {"ok": not any(row["state"] == "failed" for row in rows), "rows": rows}


def probe_lines(payload: Mapping[str, Any]) -> list:
    """The human ``probe:`` lines, one per row, in the order they ran."""
    lines = []
    for row in payload.get("rows") or []:
        field, state = row.get("field"), row.get("state")
        model = row.get("model") or ""
        if state == "ok":
            seconds = row.get("seconds")
            timing = f", {seconds}s" if seconds is not None else ""
            lines.append(f"probe: {field} ok ({model}{timing})")
        elif state == "skipped":
            lines.append(f"probe: {field} skipped ({row.get('detail')})")
        else:
            lines.append(f"probe: {field} failed: {row.get('detail')}")
            if row.get("next"):
                lines.append(f"       next: {row['next']}")
    return lines
