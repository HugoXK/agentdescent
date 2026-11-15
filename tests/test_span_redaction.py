"""Span values are redacted at the boundary, not only on `MemoryOperation` (#1063).

`#947` put `_safe_value` on `MemoryOperation.attributes` / `expected_effect`
and on the span paths its own tests walked. Three entry points still copied a
caller's mapping verbatim -- `set_attribute`, `add_event` and `start_span`'s
`attributes` -- and `to_span_attributes()` re-emitted the immutable memory
fields raw. A span leaves the process, so each of those paths is pinned here,
with the `#947` control rows kept green by `tests/test_memory_spans.py`.
"""

from __future__ import annotations

import pytest

from agentdescent.rsi_telemetry import (
    MemoryOperation,
    RSITelemetry,
    TelemetrySpan,
)

SECRET = "sk-live-abcdef123456"
REDACTED = "[redacted]"


def _telemetry() -> RSITelemetry:
    counter = iter(range(1, 1000))
    return RSITelemetry(clock=lambda: 10.0,
                        id_factory=lambda kind: f"{kind}-{next(counter)}")


def test_memory_operation_span_attributes_redact_the_immutable_fields() -> None:
    operation = MemoryOperation(
        "write", "sk-live-lesson-abcdef123456",
        precondition=SECRET, evidence_hash=SECRET, verifier=SECRET,
        reason=SECRET, attributes={"label": "kept"})

    attributes = operation.to_span_attributes()

    for key in ("memory.lesson_id", "memory.precondition",
                "memory.evidence_hash", "memory.verifier", "memory.reason"):
        assert attributes[key] == REDACTED, key
    assert attributes["label"] == "kept"

    control = MemoryOperation("write", "lesson-1", precondition="base v1",
                              evidence_hash="abc", verifier="v1")
    clean = control.to_span_attributes()
    assert clean["memory.precondition"] == "base v1"
    assert clean["memory.evidence_hash"] == "abc"
    assert clean["memory.verifier"] == "v1"


def test_set_attribute_redacts_the_value() -> None:
    span = _telemetry().start_span("op")

    span.set_attribute("note", SECRET)
    span.set_attribute("count", 3)

    assert span.attributes["note"] == REDACTED
    assert span.attributes["count"] == 3


def test_add_event_redacts_the_value() -> None:
    telemetry = _telemetry()
    span = telemetry.start_span("op")

    event = telemetry.event(span, "adopt", {"detail": SECRET, "artifact_id": "a1"})

    assert event.attributes["detail"] == REDACTED
    assert event.attributes["artifact_id"] == "a1"


def test_start_span_redacts_the_initial_attributes() -> None:
    span = _telemetry().start_span("op", attributes={"detail": SECRET,
                                                     "artifact_id": "a1"})

    assert span.attributes["detail"] == REDACTED
    assert span.attributes["artifact_id"] == "a1"


def test_a_directly_constructed_span_redacts_too() -> None:
    span = TelemetrySpan(trace_id="t", span_id="s", name="op", kind="span",
                         start=1.0, attributes={"detail": SECRET})

    assert span.attributes["detail"] == REDACTED


def test_exception_event_redacts_the_message() -> None:
    telemetry = _telemetry()

    with pytest.raises(RuntimeError):
        with telemetry.span("op") as span:
            raise RuntimeError(f"auth failed with {SECRET}")

    (event,) = span.events
    assert event.name == "exception"
    assert event.attributes["type"] == "RuntimeError"
    assert event.attributes["message"] == REDACTED
    assert SECRET not in str(span.events)


# --- a credential key is matched by component (#1070) ---------------------
#
# `_is_secret_key` used substring matching, so `token` and `secret` also
# matched `tokens`, `max_tokens`, `token_count` and `secret_free`: every
# counter a cost or budget span exists to record was dropped on the way out.
# The filter must still drop every credential name, so both lists are pinned.

MEASUREMENT_KEYS = {
    "tokens": 120,
    "max_tokens": 16,
    "input_tokens": 5,
    "output_tokens": 11,
    "token_count": 3,
    "tokens_in": 7,
    "budget_tokens": 500,
    "secret_free": False,
    "secrets_scanned": 12,
}

CREDENTIAL_KEYS = (
    "api_key", "apikey", "access_key", "secret", "client_secret", "password",
    "authorization", "private_key", "credential", "token", "api_token",
    "access_token", "auth_token", "refresh_token", "bearer_token",
)


def test_measurement_keys_survive_the_filter() -> None:
    telemetry = _telemetry()
    span = telemetry.start_span("cost", attributes=MEASUREMENT_KEYS)

    for key, value in MEASUREMENT_KEYS.items():
        assert span.attributes.get(key) == value, key

    (exported,) = telemetry.to_otel()
    for key, value in MEASUREMENT_KEYS.items():
        assert exported["attributes"].get(key) == value, key


def test_credential_keys_are_still_dropped() -> None:
    span = _telemetry().start_span(
        "cost", attributes={key: SECRET for key in CREDENTIAL_KEYS})

    assert span.attributes == {}

    for key in CREDENTIAL_KEYS:
        span.set_attribute(key, SECRET)
        assert key not in span.attributes, key

    event = span.add_event("adopt", {key: SECRET for key in CREDENTIAL_KEYS})
    assert event.attributes == {}


def test_span_round_trip_keeps_the_token_counters() -> None:
    telemetry = _telemetry()
    telemetry.start_span("x", attributes={"max_tokens": 16, "input_tokens": 5})

    (exported,) = telemetry.to_otel()
    attributes = exported["attributes"]
    assert attributes["max_tokens"] == 16
    assert attributes["input_tokens"] == 5


def test_a_credential_value_in_a_kept_key_is_still_redacted() -> None:
    span = _telemetry().start_span("cost", attributes={"max_tokens": SECRET,
                                                       "tokens": SECRET})

    assert span.attributes["max_tokens"] == REDACTED
    assert span.attributes["tokens"] == REDACTED


def test_a_memory_block_keeps_its_counters_too() -> None:
    operation = MemoryOperation("write", "lesson-1",
                                attributes={"budget_tokens": 500,
                                            "token_count": 3})

    attributes = operation.to_span_attributes()

    assert attributes["budget_tokens"] == 500
    assert attributes["token_count"] == 3


# --- a credential written as one word is still a credential (#1095) --------
#
# `#1070` matches a whole component, so a credential name that arrives as one
# word falls through all three rules: `PGPASSWORD` is libpq's password variable,
# `s3secretkey` and `AWSSecretAccessKey` need a separator to split, and
# `client_secrets` / `api_keys` are the pair with a plural `s`. The amendment
# also pins the plain plurals (`passwords`, `pgpasswords`, `db_secrets`), which
# only the last-position noun rule and the plural suffixes reach. `auth` stays a
# non-goal: it names a mode (`auth_mode`, `auth_ok`) as often as a credential.

CREDENTIAL_WORD_KEYS = (
    "PGPASSWORD", "pgpassword", "passwords", "pgpasswords", "db_passwords",
    "db_secrets", "client_secrets", "CLIENT_SECRETS", "api_keys",
    "secret_keys", "s3secretkey", "AWSSecretAccessKey", "AWS_SECRET_ACCESS_KEY",
)

#: Names that are not credentials, including the recorded `auth` non-goal.
NOT_CREDENTIAL_KEYS = (
    "REDISCLI_AUTH", "auth", "sort_key", "monkey", "max_new_tokens",
    "total_tokens", "status", "access_level",
)


def _is_secret_key(key: object) -> bool:
    from agentdescent.rsi_telemetry import _is_secret_key as predicate

    return predicate(key)


@pytest.mark.parametrize("key", CREDENTIAL_WORD_KEYS)
def test_a_credential_key_is_dropped(key: str) -> None:
    assert _is_secret_key(key) is True


@pytest.mark.parametrize("key", tuple(MEASUREMENT_KEYS) + NOT_CREDENTIAL_KEYS)
def test_the_counters_and_an_auth_mode_are_not_credentials(key: str) -> None:
    assert _is_secret_key(key) is False


def test_a_one_word_credential_never_reaches_the_export() -> None:
    telemetry = _telemetry()
    span = telemetry.start_span("cost", attributes={
        "PGPASSWORD": "hunter2", "MAX_TOKENS": 16, "secrets_scanned": 12})

    assert "PGPASSWORD" not in span.attributes
    assert span.attributes["MAX_TOKENS"] == 16
    assert span.attributes["secrets_scanned"] == 12

    (exported,) = telemetry.to_otel()
    assert "PGPASSWORD" not in exported["attributes"]
    assert exported["attributes"]["MAX_TOKENS"] == 16
    assert exported["attributes"]["secrets_scanned"] == 12
    assert "hunter2" not in str(exported)
