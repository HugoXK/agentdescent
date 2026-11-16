# RSI metrics — acceptance, cost and category frequency

A run store answers what happened; a product needs the aggregate: acceptance
rate, cost per accepted change, which categories appear most often, and a stable
text export for Prometheus.

```python
from agentdescent import alerts, metrics_from_log, to_prometheus

metrics = metrics_from_log(records)    # any iterable of decision records
print(metrics.acceptance_rate, metrics.cost_per_accepted)
print(to_prometheus(metrics))
for line in alerts(metrics, min_acceptance=0.2, max_cost_per_accepted=50):
    print("ALERT:", line)
```

- `metrics_from_records` accepts dicts or objects with `accepted` (bool),
  `category` (str) and `cost` (a mapping/object with `calls`,
  `prompt_tokens`, `completion_tokens`, `wallclock`).
- Missing fields count as zero. A malformed present field — a non-bool
  `accepted`, a negative/non-integer call count, a non-finite wall clock, a
  cost that is neither a mapping nor an object with cost fields — raises a
  `ValueError` naming the record index. These numbers drive alerts, so they are
  not silently coerced.
- `acceptance_rate`, `calls`, token totals, wall clock, `cost_per_accepted`
  (calls per accepted decision, `None` when nothing was accepted) and a category
  frequency histogram (all decisions, not only refusals).
- `to_prometheus` is deterministic. Every family has one `HELP`/`TYPE` pair;
  the per-category counter is its own family
  (`agentdescent_rsi_decisions_by_category_total`) so Prometheus/OpenMetrics
  parsers do not see two types for one sample name. Counter names use the
  `_total` suffix and label values escape backslash, quote and newline.
- Counters are snapshots over the iterable passed in, so they are only
  monotonic when the underlying log is append-only.
- `alerts` is a small, pure threshold list (minimum acceptance rate, maximum
  cost per accepted change). When calls were spent but nothing was accepted,
  `max_cost_per_accepted` still fires rather than hiding behind `None`.

All metrics are derived from decision records; no model call and no second
source of truth.

## Opt-in OTLP export

`agentdescent.otel_export` bridges a run's rounds, decisions and cost to an
OpenTelemetry collector. It is off by default and needs no dependency to import;
constructing an `OtlpExporter` does need the `[otel]` extra, which the constructor
imports.

```python
from agentdescent import metrics_from_log
from agentdescent.otel_export import (DecisionSample, RoundSample, export_run,
                                      exporter_from_env)

exporter = exporter_from_env()          # None unless OTEL_EXPORTER_OTLP_ENDPOINT is set
if exporter is not None:
    export_run(exporter, run_id="run-1", metrics=metrics_from_log(records),
               rounds=[RoundSample(1, reward=0.4, tokens=120, wallclock=2.0)],
               decisions=[DecisionSample("skill", True, calls=2,
                                         prompt_tokens=300, wallclock=1.1)])
    exporter.force_flush()              # or exporter.shutdown() when it is the last run
```

- One span per round (`agentdescent.round`) and one per decision
  (`agentdescent.decision`); the aggregate counters/gauge reuse the
  `agentdescent_rsi_*` names above, and a `agentdescent_rsi_round_reward`
  histogram carries each measured reward.
- A host can pass any object with `export_span`/`export_metric` (the
  `TelemetryExporter` protocol), so tests need no collector.
- Off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set; `OTEL_EXPORTER_OTLP_HEADERS`
  and `OTEL_SERVICE_NAME` are read too. Constructing `OtlpExporter` imports the
  SDK, so without `pip install "agentdescent[otel]"` construction itself raises
  an `ImportError` naming that line, before a run starts.
- The endpoint is checked before anything is exported: a URL carrying
  credentials (`https://user:token@host/`) is refused without the value being
  repeated in the error, and plain `http://` is accepted only for a literal
  loopback collector (`localhost`, `127.0.0.0/8`, `[::1]`). A remote collector
  needs TLS terminated in front of it. Credentials belong in
  `OTEL_EXPORTER_OTLP_HEADERS`, never in the URL: this module does not echo an
  accepted endpoint, but the SDK's httpx errors quote the request URL, so a
  token in the path or query would still reach a log.
- Delivery is per exporter and explicit. Each `OtlpExporter` owns its tracer and
  meter providers, so a second exporter in the same process does not export
  through the first one's endpoint or headers. The SDK batches spans for 5 s and
  exports metrics on a 60 s interval, and `export_run` counts records handed
  over, not delivered: call `force_flush()` before a short process exits, or
  `shutdown()` when the exporter is done, otherwise the queue and the pending
  interval are lost.
- Nothing free-form is exported: samples carry numbers and a category, and the
  writer copies a fixed attribute set, so prompts and model responses cannot
  ride along by default. The three string attributes (`run.id`, `run.tenant`,
  `decision.category`) are caller-supplied identifiers, not content; that
  guarantee belongs to `export_run`, while an `ExportedSpan` handed straight to
  `export_span` has its `attributes` copied verbatim, so a caller building one
  by hand owns what goes in it.
- The wire path is exercised in CI, not only faked: the `otel-wire` job installs
  the `[otel]` extra and runs `scripts/otel_wire_smoke.py`, which exports one
  span and one metric to a closed port on `127.0.0.1` and asserts the refusal is
  reported and contained — `export_run` still returns its count, `force_flush()`
  and `shutdown()` still return, and nothing escapes.
- `export_span` copies `ExportedSpan.attributes` **verbatim**: it neither drops
  nor invents a key, so a caller that builds a span by hand owns its contents,
  and the fixed attribute set above is `export_run`'s guarantee alone
  (`tests/test_otel_wire.py`, `tests/test_otel_export.py`).
