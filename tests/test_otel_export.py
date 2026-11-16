"""The opt-in OTLP bridge, pinned without a collector (#923).

A real collector smoke test is documented as *not run*: the CI suite is offline
and the `otel` extra is not installed there. Everything below asserts the shape
a host would see -- span names and attributes, then metric names -- through a
fake exporter the bridge accepts as a `TelemetryExporter`.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from agentdescent import otel_export
from agentdescent.otel_export import (
    DecisionSample,
    ExportedMetric,
    ExportedSpan,
    RoundSample,
    export_run,
    exporter_from_env,
)
from agentdescent.rsi_metrics import metrics_from_records, to_prometheus

ROOT = pathlib.Path(__file__).resolve().parent.parent


class FakeExporter:
    """A host's exporter, so the test needs no collector and no network."""

    def __init__(self) -> None:
        self.spans: list = []
        self.metrics: list = []

    def export_span(self, span: ExportedSpan) -> None:
        self.spans.append(span)

    def export_metric(self, metric: ExportedMetric) -> None:
        self.metrics.append(metric)


ROUNDS = (
    RoundSample(1, reward=0.2, committed=1, rejected=2, tokens=90,
                wallclock=1.5, start=10.0, end=11.5),
    RoundSample(2, reward=0.35, committed=2, rejected=1, tokens=120,
                wallclock=2.0, start=11.5, end=13.5),
)

DECISIONS = (
    DecisionSample("skill", True, calls=3, prompt_tokens=300,
                   completion_tokens=60, wallclock=1.2, start=10.1, end=11.3),
    DecisionSample("prompt", False, calls=1, prompt_tokens=40,
                   completion_tokens=8, wallclock=0.2, start=11.6, end=11.8),
)


def _metrics():
    records = [
        {"accepted": d.accepted, "category": d.category,
         "cost": {"calls": d.calls, "prompt_tokens": d.prompt_tokens,
                  "completion_tokens": d.completion_tokens,
                  "wallclock": d.wallclock}}
        for d in DECISIONS
    ]
    return metrics_from_records(records)


def _export(rounds=ROUNDS, decisions=DECISIONS, **kwargs):
    exporter = FakeExporter()
    export_run(exporter, run_id="run-1", metrics=_metrics(),
               rounds=rounds, decisions=decisions, tenant="acme", **kwargs)
    return exporter


def test_a_small_run_exports_one_span_per_round_and_per_decision() -> None:
    exporter = _export()

    assert [span.name for span in exporter.spans] == [
        "agentdescent.round", "agentdescent.round",
        "agentdescent.decision", "agentdescent.decision",
    ]
    first = exporter.spans[0]
    assert first.attributes == {
        "run.id": "run-1", "run.tenant": "acme", "round.number": 1,
        "round.reward": 0.2, "round.committed": 1, "round.rejected": 2,
        "round.tokens": 90, "round.wallclock": 1.5,
    }
    assert (first.start, first.end) == (10.0, 11.5)
    decision = exporter.spans[2]
    assert decision.attributes == {
        "run.id": "run-1", "run.tenant": "acme", "decision.category": "skill",
        "decision.accepted": True, "decision.calls": 3,
        "decision.prompt_tokens": 300, "decision.completion_tokens": 60,
        "decision.wallclock": 1.2,
    }


def test_the_exported_metrics_reuse_the_rsi_metrics_families() -> None:
    exporter = _export()

    by_name = {metric.name: metric for metric in exporter.metrics}
    published = to_prometheus(_metrics())
    for name in set(by_name) - {"agentdescent_rsi_round_reward"}:
        assert name in published, name     # same family names as the text export

    assert by_name["agentdescent_rsi_decisions_total"].value == 2
    assert by_name["agentdescent_rsi_accepted_total"].value == 1
    assert by_name["agentdescent_rsi_rejected_total"].value == 1
    assert by_name["agentdescent_rsi_calls_total"].value == 4
    assert by_name["agentdescent_rsi_prompt_tokens_total"].value == 340
    assert by_name["agentdescent_rsi_completion_tokens_total"].value == 68
    assert by_name["agentdescent_rsi_acceptance_rate"].value == pytest.approx(0.5)
    assert by_name["agentdescent_rsi_cost_per_accepted"].value == pytest.approx(4.0)

    rewards = [metric for metric in exporter.metrics
               if metric.name == "agentdescent_rsi_round_reward"]
    assert [metric.value for metric in rewards] == [0.2, 0.35]
    assert all(metric.kind == "histogram" for metric in rewards)


def test_an_unmeasured_reward_is_not_a_zero() -> None:
    exporter = _export(rounds=(RoundSample(1, wallclock=1.0,
                                           start=1.0, end=2.0),))

    assert "round.reward" not in exporter.spans[0].attributes
    assert not [m for m in exporter.metrics
                if m.name == "agentdescent_rsi_round_reward"]


def test_nothing_prompt_shaped_is_exported_by_default() -> None:
    exporter = _export()

    allowed = {
        "run.id", "run.tenant", "round.number", "round.reward",
        "round.committed", "round.rejected", "round.tokens", "round.wallclock",
        "decision.category", "decision.accepted", "decision.calls",
        "decision.prompt_tokens", "decision.completion_tokens",
        "decision.wallclock",
    }
    for span in exporter.spans:
        assert set(span.attributes) <= allowed, span.name
        for value in span.attributes.values():
            assert not (isinstance(value, str) and " " in value), value


def test_the_exporter_is_off_unless_an_endpoint_is_configured() -> None:
    assert exporter_from_env({}) is None
    assert exporter_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": ""}) is None


@pytest.fixture
def missing_sdk(monkeypatch):
    """Make ``import opentelemetry`` fail even when the extra is installed.

    The `otel-wire` leg installs `[otel]`, so a probe-and-skip row would stop
    testing the fail-fast contract in exactly the environment that has the SDK
    (#1083). ``None`` in ``sys.modules`` is the interpreter's own "import
    halted" marker, so this walks the real ImportError path and not a fake
    seam: `_load_otel` catches it and re-raises with the install line.
    """
    for name in [n for n in sys.modules
                 if n == "opentelemetry" or n.startswith("opentelemetry.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "opentelemetry", None)


def test_a_configured_endpoint_needs_the_extra_at_construction(
        missing_sdk) -> None:
    """Constructing the exporter imports the SDK, so a missing extra fails
    before a run starts instead of on the first span written -- asserted with
    the SDK absent, whether or not this host installed it."""
    with pytest.raises(ImportError) as excinfo:
        exporter_from_env(
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    assert "agentdescent[otel]" in str(excinfo.value)

    with pytest.raises(ImportError) as excinfo:   # and the direct entry point
        otel_export.OtlpExporter("http://127.0.0.1:4318")
    assert "agentdescent[otel]" in str(excinfo.value)


def test_the_install_line_is_named_when_the_extra_really_is_absent() -> None:
    """One real-import row: skipped only where the SDK is genuinely present."""
    try:
        otel_export._load_otel()
    except ImportError as exc:
        assert "agentdescent[otel]" in str(exc)
    else:
        pytest.skip("the [otel] extra is installed here")


@pytest.mark.parametrize("endpoint", [
    "https://user:token@collector.example:4318",
    "https://user:token@localhost:4318",
    "http://user:token@localhost:4318",
])
def test_an_endpoint_with_credentials_in_the_url_is_refused(endpoint) -> None:
    """httpx quotes the request URL in its errors, so a userinfo endpoint would
    put the token in a log on the first 401 or timeout. Refused, never echoed."""
    with pytest.raises(ValueError) as excinfo:
        otel_export.OtlpExporter(endpoint)
    message = str(excinfo.value)
    assert "token" not in message
    assert "user:token" not in message
    assert "credential" in message.lower() or "userinfo" in message.lower()


@pytest.mark.parametrize("endpoint", [
    "http://collector.example.com:4318",
    "http://10.0.0.5:4318",
    "http://localhost.evil.example:4318",
])
def test_a_plaintext_endpoint_off_the_loopback_is_refused(endpoint) -> None:
    """Only a literal loopback collector may be plain http; the remedy named is
    TLS termination, not a switch."""
    with pytest.raises(ValueError) as excinfo:
        otel_export.OtlpExporter(endpoint)
    message = str(excinfo.value)
    assert "loopback" in message.lower()
    assert "TLS" in message


@pytest.mark.parametrize("endpoint", [
    "http://localhost:4318",
    "http://127.0.0.1:4318",
    "http://127.1.2.3:4318",
    "http://[::1]:4318",
])
def test_a_loopback_collector_may_be_plain_http(endpoint, monkeypatch) -> None:
    """Loopback http stays legal: the endpoint is accepted and kept as given.

    The SDK seam is stubbed, so this row asserts the bridge's own decision and
    opens no live provider pointed at `127.0.0.1:4318` -- before #1083 it built
    a real exporter on a host with the extra and then skipped itself.
    """
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    exporter = otel_export.OtlpExporter(endpoint)
    assert exporter.endpoint == endpoint


def test_the_environment_path_refuses_a_refused_endpoint_too() -> None:
    with pytest.raises(ValueError):
        exporter_from_env(
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example.com:4318"})


def test_importing_the_bridge_does_not_pull_the_extra() -> None:
    code = ("import sys, agentdescent, agentdescent.otel_export; "
            "assert 'opentelemetry' not in sys.modules; print('ok')")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


# --- the SDK seam -----------------------------------------------------------
#
# The provider wiring is the part that has to be right per instance, and the
# `[otel]` extra is not installed in CI, so these rows stand in for the SDK at
# `otel_export._load_otel` and inspect what the bridge does with it. They say
# nothing about the SDK's own behaviour, which no offline test can claim -- see
# `Not run:` in the PR body.


class _FakeSpan:
    def __init__(self, name, start_time, attributes) -> None:
        self.name = name
        self.start_time = start_time
        self.attributes = dict(attributes)
        self.status = None
        self.end_time = None

    def set_status(self, status) -> None:
        self.status = status

    def end(self, end_time=None) -> None:
        self.end_time = end_time


class _FakeTracer:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.spans = []

    def start_span(self, name, start_time=None, attributes=None):
        span = _FakeSpan(name, start_time, attributes or {})
        self.spans.append(span)
        return span


class _FakeCounter:
    """The SDK gives a counter ``add``, a gauge ``set``, a histogram ``record``.

    One fake with all three methods would let a wrong call pass, which is how
    ``Histogram.add`` survived to the first real export (#1083); each kind here
    carries only its own method, so a wrong call is an AttributeError.
    """

    def __init__(self) -> None:
        self.added = []

    def add(self, value, attributes) -> None:
        self.added.append((value, dict(attributes)))


class _FakeGauge:
    def __init__(self) -> None:
        self.set_values = []

    def set(self, value, attributes) -> None:
        self.set_values.append((value, dict(attributes)))


class _FakeHistogram:
    def __init__(self) -> None:
        self.recorded = []

    def record(self, value, attributes) -> None:
        self.recorded.append((value, dict(attributes)))


class _FakeMeter:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.instruments = {}

    def _instrument(self, name, factory):
        return self.instruments.setdefault(name, factory())

    def create_counter(self, name, unit=None):
        return self._instrument(name, _FakeCounter)

    def create_gauge(self, name, unit=None):
        return self._instrument(name, _FakeGauge)

    def create_histogram(self, name, unit=None):
        return self._instrument(name, _FakeHistogram)


class _FakeSignalExporter:
    """One per signal, so a test can see which endpoint it was built for."""

    def __init__(self, endpoint=None, headers=None) -> None:
        self.endpoint = endpoint
        self.headers = headers


class _FakeProcessor:
    def __init__(self, exporter) -> None:
        self.exporter = exporter


class _FakeReader:
    def __init__(self, exporter) -> None:
        self.exporter = exporter


class _FakeTracerProvider:
    def __init__(self, resource=None) -> None:
        self.resource = resource
        self.processors = []
        self.tracer = None
        self.flushed = []
        self.stopped = False

    def add_span_processor(self, processor) -> None:
        self.processors.append(processor)

    def get_tracer(self, name):
        self.tracer = _FakeTracer(self)
        return self.tracer

    def force_flush(self, timeout_millis=3000):
        self.flushed.append(timeout_millis)
        return True

    def shutdown(self) -> None:
        self.stopped = True


class _FakeMeterProvider:
    def __init__(self, resource=None, metric_readers=()) -> None:
        self.resource = resource
        self.readers = list(metric_readers)
        self.meter = None
        self.flushed = []
        self.stopped = False

    def get_meter(self, name):
        self.meter = _FakeMeter(self)
        return self.meter

    def force_flush(self, timeout_millis=3000):
        self.flushed.append(timeout_millis)
        return True

    def shutdown(self) -> None:
        self.stopped = True


class _FakeResource:
    @staticmethod
    def create(attributes):
        return dict(attributes)


def _fake_otel():
    return {
        "TracerProvider": _FakeTracerProvider,
        "MeterProvider": _FakeMeterProvider,
        "Resource": _FakeResource,
        "BatchSpanProcessor": _FakeProcessor,
        "PeriodicExportingMetricReader": _FakeReader,
        "OTLPSpanExporter": _FakeSignalExporter,
        "OTLPMetricExporter": _FakeSignalExporter,
        "Status": lambda code, description=None: (code, description),
        "StatusCode": type("StatusCode", (), {"ERROR": "ERROR"}),
    }


def test_two_exporters_do_not_share_a_provider(monkeypatch) -> None:
    """A second exporter must not export through the first one's endpoint.

    The SDK keeps the first provider installed process-wide, so a bridge that
    installed a global provider and then asked the global for a tracer sends
    tenant B's identifiers to tenant A's collector. Each instance owns its
    providers, so a span written through one reaches only that one's tracer.
    """
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    first = otel_export.OtlpExporter("https://a.example:4318",
                                     headers={"x-tenant": "a"})
    second = otel_export.OtlpExporter("https://b.example:4318",
                                      headers={"x-tenant": "b"})

    first.export_span(ExportedSpan("agentdescent.round", {"run.id": "a"},
                                   1.0, 2.0))
    second.export_span(ExportedSpan("agentdescent.round", {"run.id": "b"},
                                    1.0, 2.0))

    assert first._tracer_provider is not second._tracer_provider
    assert first._meter_provider is not second._meter_provider
    assert first._tracer.provider is first._tracer_provider
    assert second._tracer.provider is second._tracer_provider

    assert first._tracer_provider.processors[0].exporter.endpoint == (
        "https://a.example:4318/v1/traces")
    assert second._tracer_provider.processors[0].exporter.endpoint == (
        "https://b.example:4318/v1/traces")
    assert first._meter_provider.readers[0].exporter.endpoint == (
        "https://a.example:4318/v1/metrics")
    assert second._meter_provider.readers[0].exporter.endpoint == (
        "https://b.example:4318/v1/metrics")
    assert second._tracer_provider.processors[0].exporter.headers == {
        "x-tenant": "b"}

    assert [span.attributes["run.id"] for span in first._tracer.spans] == ["a"]
    assert [span.attributes["run.id"] for span in second._tracer.spans] == ["b"]


def test_force_flush_and_shutdown_close_only_this_exporter(monkeypatch) -> None:
    """A short process loses the batch queue unless it flushes; one exporter
    shutting down must not close another host's providers."""
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    first = otel_export.OtlpExporter("https://a.example:4318")
    second = otel_export.OtlpExporter("https://b.example:4318")
    span = ExportedSpan("agentdescent.round", {"run.id": "run-1"}, 1.0, 2.0)
    first.export_span(span)
    second.export_span(span)

    assert first.force_flush(2500) is True
    assert first._tracer_provider.flushed == [2500]
    assert first._meter_provider.flushed == [2500]
    assert second._tracer_provider.flushed == []

    first.shutdown()
    assert first._tracer_provider.stopped is True
    assert first._meter_provider.stopped is True
    assert second._tracer_provider.stopped is False
    assert second._meter_provider.stopped is False


def test_the_instrument_methods_match_the_sdk(monkeypatch) -> None:
    """Counter ``add``, gauge ``set``, histogram ``record`` -- the SDK's names.

    Each fake instrument carries only its own kind's method, so a wrong call is
    an AttributeError here instead of on the first real export; that is how
    ``Histogram.add`` was found after the fakes had hidden it (#1083).
    """
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    exporter = otel_export.OtlpExporter("https://a.example:4318")

    export_run(exporter, run_id="run-1", metrics=_metrics(),
               rounds=(RoundSample(1, reward=0.25, start=1.0, end=2.0),),
               decisions=(DecisionSample("skill", True, calls=1,
                                         start=2.0, end=2.1),))

    instruments = exporter._meter.instruments
    assert instruments["agentdescent_rsi_round_reward"].recorded == [(0.25, {
        "run.id": "run-1"})]
    assert instruments["agentdescent_rsi_decisions_total"].added == [(2.0, {})]
    assert instruments["agentdescent_rsi_acceptance_rate"].set_values


def test_export_span_copies_attributes_verbatim_and_invents_nothing(monkeypatch) -> None:
    """``export_span`` copies what it is given: no filtering, no invented keys.

    So the no-content guarantee is ``export_run``'s (its writer builds a fixed
    attribute set), and a caller handing the exporter its own ``ExportedSpan``
    owns every key in it -- load-bearing while ``rsi_telemetry`` spans can feed
    the exporter with the redaction question in #947 still open (#1083).
    """
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    exporter = otel_export.OtlpExporter("https://a.example:4318")
    attributes = {"run.id": "run-1", "caller.note": "free text, spaces, 42"}
    span = ExportedSpan("agentdescent.round", attributes, 1.0, 2.0)

    exporter.export_span(span)

    recorded = exporter._tracer.spans[-1]
    assert recorded.attributes == attributes          # verbatim, nothing dropped
    assert recorded.attributes is not attributes      # a copy, not an alias
    assert "caller.note" in recorded.attributes       # nothing invented either
