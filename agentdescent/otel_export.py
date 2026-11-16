"""An opt-in OTLP bridge for a run's rounds, decisions and cost (#923).

``rsi_telemetry`` already shapes a run as spans and ``rsi_metrics`` already
aggregates its decisions, but neither leaves the process. This module is the
piece between them and a collector:

- :class:`TelemetryExporter` is the one method pair a host implements, or fakes
  in a test, so the bridge itself needs no collector and no network;
- :func:`export_run` writes one span per round and one per decision, and
  re-exports the :mod:`agentdescent.rsi_metrics` families under the names
  :func:`agentdescent.rsi_metrics.to_prometheus` already publishes, so a
  dashboard reads one set of names whichever export it consumes;
- :func:`exporter_from_env` is the switch, and it is **off by default**: with no
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` it returns ``None`` and nothing is exported;
- :class:`OtlpExporter` is the only place the ``[otel]`` extra is imported, in
  its constructor: importing this module needs nothing extra, and a missing
  extra raises the install line at construction, before a run starts. Each
  instance owns its tracer and meter providers, because the SDK keeps the first
  provider installed process-wide: a second exporter must not export through
  the first one's endpoint and headers;
- :meth:`OtlpExporter.force_flush` and :meth:`OtlpExporter.shutdown` touch only
  this instance. The SDK batches spans (5 s) and exports metrics on an interval
  (60 s), so without a flush a short process loses what it handed over.

Importing this module is standard-library only. An install without the extra
keeps importing the package and running normally.

Nothing free-form rides along: the sample types carry numbers and a category
name, and :func:`export_run` writes a fixed attribute set, so a prompt or a model
response cannot be exported by accident.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, runtime_checkable
from urllib.parse import urlsplit

from .rsi_metrics import RSIMetrics

__all__ = [
    "DecisionSample",
    "ExportedMetric",
    "ExportedSpan",
    "OtlpExporter",
    "RoundSample",
    "TelemetryExporter",
    "export_run",
    "exporter_from_env",
]

#: Same family names as ``rsi_metrics.to_prometheus``; a dashboard should not
#: have to know which export path produced a number (#923).
DECISIONS_TOTAL = "agentdescent_rsi_decisions_total"
ACCEPTED_TOTAL = "agentdescent_rsi_accepted_total"
REJECTED_TOTAL = "agentdescent_rsi_rejected_total"
ACCEPTANCE_RATE = "agentdescent_rsi_acceptance_rate"
CALLS_TOTAL = "agentdescent_rsi_calls_total"
PROMPT_TOKENS_TOTAL = "agentdescent_rsi_prompt_tokens_total"
COMPLETION_TOKENS_TOTAL = "agentdescent_rsi_completion_tokens_total"
WALLCLOCK_SECONDS_TOTAL = "agentdescent_rsi_wallclock_seconds_total"
COST_PER_ACCEPTED = "agentdescent_rsi_cost_per_accepted"
ROUND_REWARD = "agentdescent_rsi_round_reward"

ROUND_SPAN = "agentdescent.round"
DECISION_SPAN = "agentdescent.decision"
DEFAULT_SERVICE_NAME = "agentdescent"


@dataclass(frozen=True)
class ExportedSpan:
    """One span as a host's exporter receives it; times are epoch seconds."""

    name: str
    attributes: Dict[str, Any]
    start: float
    end: float
    status: str = "ok"


@dataclass(frozen=True)
class ExportedMetric:
    """One metric record: ``kind`` is ``counter``, ``gauge`` or ``histogram``."""

    name: str
    kind: str
    value: float
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoundSample:
    """What one round contributes to the export.

    Every field is a number or a flag: there is no place to put a prompt, a
    completion or a free-form note, which is what keeps the default export
    privacy-safe (#923).
    """

    number: int
    reward: Optional[float] = None
    committed: int = 0
    rejected: int = 0
    tokens: int = 0
    wallclock: float = 0.0
    start: float = 0.0
    end: float = 0.0


@dataclass(frozen=True)
class DecisionSample:
    """What one decision contributes: its category, verdict and cost."""

    category: str
    accepted: bool
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wallclock: float = 0.0
    start: float = 0.0
    end: float = 0.0


@runtime_checkable
class TelemetryExporter(Protocol):
    """What a host implements to receive a run's spans and metrics.

    A fake with two list-appending methods is enough for a test, so the suite
    never needs a collector or the ``[otel]`` extra.
    """

    def export_span(self, span: ExportedSpan) -> None:
        ...

    def export_metric(self, metric: ExportedMetric) -> None:
        ...


def _round_attributes(run_id: str, tenant: Optional[str],
                      sample: RoundSample) -> Dict[str, Any]:
    attributes: Dict[str, Any] = {"run.id": str(run_id)}
    if tenant:
        attributes["run.tenant"] = str(tenant)
    attributes["round.number"] = int(sample.number)
    if sample.reward is not None:
        attributes["round.reward"] = float(sample.reward)
    attributes.update({
        "round.committed": int(sample.committed),
        "round.rejected": int(sample.rejected),
        "round.tokens": int(sample.tokens),
        "round.wallclock": float(sample.wallclock),
    })
    return attributes


def _decision_attributes(run_id: str, tenant: Optional[str],
                         sample: DecisionSample) -> Dict[str, Any]:
    attributes: Dict[str, Any] = {"run.id": str(run_id)}
    if tenant:
        attributes["run.tenant"] = str(tenant)
    attributes.update({
        "decision.category": str(sample.category),
        "decision.accepted": bool(sample.accepted),
        "decision.calls": int(sample.calls),
        "decision.prompt_tokens": int(sample.prompt_tokens),
        "decision.completion_tokens": int(sample.completion_tokens),
        "decision.wallclock": float(sample.wallclock),
    })
    return attributes


def _aggregate_metrics(metrics: RSIMetrics) -> List[ExportedMetric]:
    out = [
        ExportedMetric(DECISIONS_TOTAL, "counter", float(metrics.decisions)),
        ExportedMetric(ACCEPTED_TOTAL, "counter", float(metrics.accepted)),
        ExportedMetric(REJECTED_TOTAL, "counter", float(metrics.rejected)),
        ExportedMetric(ACCEPTANCE_RATE, "gauge", float(metrics.acceptance_rate)),
        ExportedMetric(CALLS_TOTAL, "counter", float(metrics.calls)),
        ExportedMetric(PROMPT_TOKENS_TOTAL, "counter",
                       float(metrics.prompt_tokens)),
        ExportedMetric(COMPLETION_TOKENS_TOTAL, "counter",
                       float(metrics.completion_tokens)),
        ExportedMetric(WALLCLOCK_SECONDS_TOTAL, "counter",
                       float(metrics.wallclock)),
    ]
    # ``None`` is "nothing was accepted", not zero calls per accept: skip it
    # rather than publishing a number the text export refuses to invent.
    if metrics.cost_per_accepted is not None:
        out.append(ExportedMetric(COST_PER_ACCEPTED, "gauge",
                                  float(metrics.cost_per_accepted)))
    return out


def export_run(exporter: TelemetryExporter, *, run_id: str,
               metrics: Optional[RSIMetrics] = None,
               rounds: Sequence[RoundSample] = (),
               decisions: Sequence[DecisionSample] = (),
               tenant: Optional[str] = None) -> int:
    """Export one run; return how many records were handed to ``exporter``.

    One span per round and one per decision, then the aggregate families from
    ``metrics`` (when given). An unmeasured round reward is absent rather than
    written as zero, and no prompt- or response-shaped value is ever written.
    """
    exported = 0
    for sample in rounds:
        exporter.export_span(ExportedSpan(
            name=ROUND_SPAN, attributes=_round_attributes(run_id, tenant, sample),
            start=float(sample.start), end=float(sample.end)))
        exported += 1
        if sample.reward is not None:
            exporter.export_metric(ExportedMetric(
                ROUND_REWARD, "histogram", float(sample.reward),
                {"run.id": str(run_id)}))
            exported += 1
    for sample in decisions:
        exporter.export_span(ExportedSpan(
            name=DECISION_SPAN,
            attributes=_decision_attributes(run_id, tenant, sample),
            start=float(sample.start), end=float(sample.end)))
        exported += 1
    if metrics is not None:
        for metric in _aggregate_metrics(metrics):
            exporter.export_metric(metric)
            exported += 1
    return exported


def _is_loopback(host: str) -> bool:
    """Literal loopback only: no name resolution, so no DNS-based bypass."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _endpoint_problem(endpoint: str) -> Optional[str]:
    """Why an endpoint is refused, or ``None`` when it is acceptable.

    The message never quotes the endpoint: a URL can carry a token, and a
    refusal goes to the same logs the URL must not reach. The one non-TLS
    allowance is a literal loopback collector; every other plain-``http``
    endpoint is refused with TLS termination named as the remedy (no switch).
    """
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return "the endpoint is not a valid URL"
    if parts.scheme not in ("http", "https"):
        return "the endpoint must be an http(s) URL"
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        return ("the endpoint must not carry credentials in the URL; put them "
                "in OTEL_EXPORTER_OTLP_HEADERS instead")
    host = parts.hostname or ""
    if not host:
        return "the endpoint needs a host"
    if parts.scheme == "http" and not _is_loopback(host):
        return ("plain http:// is only accepted for a loopback collector; "
                "terminate TLS in front of a remote collector instead")
    return None


def _refuse_bad_endpoint(endpoint: str) -> None:
    problem = _endpoint_problem(endpoint)
    if problem is not None:
        raise ValueError("refusing the OTLP endpoint: " + problem)


def exporter_from_env(environ: Optional[Mapping[str, str]] = None
                      ) -> Optional[TelemetryExporter]:
    """The opt-in switch: ``None`` unless ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set."""
    env = os.environ if environ is None else environ
    endpoint = str(env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if not endpoint:
        return None
    _refuse_bad_endpoint(endpoint)
    headers: Dict[str, str] = {}
    for pair in str(env.get("OTEL_EXPORTER_OTLP_HEADERS") or "").split(","):
        key, _, value = pair.partition("=")
        if key.strip():
            headers[key.strip()] = value.strip()
    service = str(env.get("OTEL_SERVICE_NAME") or "").strip()
    return OtlpExporter(endpoint, headers=headers,
                        service_name=service or DEFAULT_SERVICE_NAME)


_OTEL_INSTALL_HINT = (
    "OTLP export needs the optional extra: pip install 'agentdescent[otel]'")


def _load_otel() -> Dict[str, Any]:
    """The SDK classes the exporter needs, imported by the constructor.

    Behind a function so a test can stand a fake SDK in: the ``[otel]`` extra is
    not installed in CI, and the per-instance provider wiring is the part that
    has to be right.
    """
    try:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter)
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter)
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace import Status, StatusCode
    except ImportError as exc:
        raise ImportError(_OTEL_INSTALL_HINT) from exc
    return {
        "TracerProvider": TracerProvider,
        "MeterProvider": MeterProvider,
        "Resource": Resource,
        "BatchSpanProcessor": BatchSpanProcessor,
        "PeriodicExportingMetricReader": PeriodicExportingMetricReader,
        "OTLPSpanExporter": OTLPSpanExporter,
        "OTLPMetricExporter": OTLPMetricExporter,
        "Status": Status,
        "StatusCode": StatusCode,
    }


class OtlpExporter:
    """OTLP/HTTP through the OpenTelemetry SDK, imported at construction.

    Importing this module needs nothing extra; constructing this class imports
    the SDK, so a missing extra raises the install line here, before a run
    starts, rather than on the first span a caller writes.

    Each instance owns its tracer and meter providers. The SDK keeps the *first*
    provider installed process-wide, so a bridge that installed a global
    provider and then asked the global for a tracer would export a second
    tenant's identifiers through the first tenant's endpoint and headers.

    Call :meth:`force_flush` (or :meth:`shutdown`) before a short process exits:
    the SDK batches spans for 5 s and exports metrics on a 60 s interval, so the
    records :func:`export_run` counts have been handed over, not delivered.
    """

    def __init__(self, endpoint: str, *, headers: Optional[Mapping[str, str]] = None,
                 service_name: str = DEFAULT_SERVICE_NAME) -> None:
        endpoint = str(endpoint).strip()
        _refuse_bad_endpoint(endpoint)
        self.endpoint = endpoint.rstrip("/")
        self.headers = dict(headers or {})
        self.service_name = service_name
        self._instruments: Dict[str, Any] = {}
        self._stopped = False
        self._otel = _load_otel()    # fail at construction, not mid-run
        resource = self._otel["Resource"].create({"service.name": service_name})
        self._tracer_provider = self._otel["TracerProvider"](resource=resource)
        self._tracer_provider.add_span_processor(self._otel["BatchSpanProcessor"](
            self._otel["OTLPSpanExporter"](endpoint=self._url("traces"),
                                           headers=self.headers or None)))
        self._meter_provider = self._otel["MeterProvider"](
            resource=resource,
            metric_readers=[self._otel["PeriodicExportingMetricReader"](
                self._otel["OTLPMetricExporter"](endpoint=self._url("metrics"),
                                                 headers=self.headers or None))])
        self._tracer = self._tracer_provider.get_tracer("agentdescent")
        self._meter = self._meter_provider.get_meter("agentdescent")

    def _url(self, signal: str) -> str:
        return f"{self.endpoint}/v1/{signal}"

    def force_flush(self, timeout_millis: int = 3000) -> bool:
        """Flush this instance's batched spans and pending metrics now."""
        results = []
        for provider in (self._tracer_provider, self._meter_provider):
            if provider is not None:
                results.append(bool(provider.force_flush(timeout_millis)))
        return all(results) if results else True

    def shutdown(self) -> None:
        """Flush, then close this instance's providers; other exporters keep theirs."""
        if self._stopped:
            return
        self.force_flush()
        self._stopped = True
        for provider in (self._tracer_provider, self._meter_provider):
            if provider is not None:
                provider.shutdown()

    def export_span(self, span: ExportedSpan) -> None:
        status, status_code = self._otel["Status"], self._otel["StatusCode"]
        current = self._tracer.start_span(
            span.name, start_time=int(float(span.start) * 1_000_000_000),
            attributes=dict(span.attributes))
        if span.status not in ("ok", "unset"):
            current.set_status(status(status_code.ERROR, span.status))
        current.end(end_time=int(float(span.end) * 1_000_000_000))

    def export_metric(self, metric: ExportedMetric) -> None:
        instrument = self._instruments.get(metric.name)
        if instrument is None:
            # ``create_gauge`` exists at the pinned floor: present in the SDK
            # source at v1.23.0, v1.24.0 and v1.25.0 (re-checked when the floor
            # moves), so >=1.24 needs no fallback here.
            instrument = {
                "counter": self._meter.create_counter,
                "gauge": self._meter.create_gauge,
                "histogram": self._meter.create_histogram,
            }[metric.kind](metric.name, unit="1")
            self._instruments[metric.name] = instrument
        value, attributes = float(metric.value), dict(metric.attributes)
        if metric.kind == "gauge":
            instrument.set(value, attributes)
        elif metric.kind == "histogram":
            # ``record`` is the SDK's histogram method; ``add`` belongs to
            # counters. The fake SDK used to give its histogram an ``add``, so
            # the first real export raised AttributeError mid-run (#1083).
            instrument.record(value, attributes)
        else:
            instrument.add(value, attributes)
