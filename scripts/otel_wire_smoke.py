#!/usr/bin/env python3
"""Exercise the real OTLP wire path against a closed port on 127.0.0.1 (#1083).

The offline suite stands a fake SDK in at ``otel_export._load_otel``, so nothing
there proves what the *real* exporter does when the collector is unreachable and
``export_span``/``export_metric`` are marked ``# pragma: no cover``. This script
is run by the ``otel-wire`` CI job with the ``[otel]`` extra installed:

1. it picks a port on 127.0.0.1 that has no listener,
2. exports one round span, one reward histogram and one decision span through an
   ``OtlpExporter`` built the way a host builds it (``exporter_from_env``),
3. and asserts the documented promise: ``export_run`` still returns its count,
   no exception escapes, ``force_flush()``/``shutdown()`` do not raise, and the
   SDK *logs* the refused connection -- which is what makes this a wire-path
   test rather than a no-op.

Exit status is 0 only when all of that holds; anything else is a promise that
broke and fails the job.
"""

from __future__ import annotations

import logging
import socket
import sys
import traceback

from agentdescent.otel_export import (
    DecisionSample,
    RoundSample,
    export_run,
    exporter_from_env,
)


def _closed_port() -> int:
    """A port on 127.0.0.1 that is free now and has no listener when we use it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class _Capture(logging.Handler):
    """Keep the SDK's own diagnostics, which are the only proof of the attempt."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.messages.append(record.getMessage())
        except Exception:                     # never let the probe itself fail
            self.messages.append(repr(record.msg))


def _mentions_a_refused_connection(messages: list[str]) -> bool:
    haystack = "\n".join(messages).lower()
    return any(marker in haystack for marker in (
        "connection refused",
        "connectionrefused",
        "failed to export",
        "max retries",
    ))


def main() -> int:
    port = _closed_port()
    endpoint = f"http://127.0.0.1:{port}"
    capture = _Capture()
    logger = logging.getLogger("opentelemetry")
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)

    problems: list[str] = []

    try:                                       # construction is a run-start step
        exporter = exporter_from_env(
            {"OTEL_EXPORTER_OTLP_ENDPOINT": endpoint})
    except ImportError as exc:
        print(f"the [otel] extra is not installed: {exc}", file=sys.stderr)
        print("this job must run `pip install -e \".[otel]\"` first", file=sys.stderr)
        return 2

    try:
        exported = export_run(
            exporter,
            run_id="wire-1",
            rounds=[RoundSample(1, reward=0.5, tokens=10, wallclock=1.0,
                                start=1.0, end=2.0)],
            decisions=[DecisionSample("skill", True, calls=1, prompt_tokens=5,
                                      wallclock=0.1, start=2.0, end=2.1)],
        )
        flushed = exporter.force_flush(3000)
    except Exception:                          # the promise under test
        print("export_run/force_flush raised out:", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        try:
            exporter.shutdown()
        except Exception:
            print("shutdown() raised out:", file=sys.stderr)
            traceback.print_exc()
            problems.append("shutdown raised")

    # 1 round span + 1 reward histogram + 1 decision span; no aggregate metrics
    # were passed, so nothing else is counted.
    if exported != 3:
        problems.append(f"export_run returned {exported}, expected 3")
    if not isinstance(flushed, bool):
        problems.append(f"force_flush returned {type(flushed).__name__}, not bool")
    if not _mentions_a_refused_connection(capture.messages):
        problems.append("the SDK never logged a refused connection: the wire "
                        "path was not attempted")
    if any("traceback" in message.lower() for message in capture.messages):
        problems.append("the SDK logged a traceback instead of a handled error")

    print(f"endpoint={endpoint} exported={exported} force_flush={flushed} "
          f"sdk-messages={len(capture.messages)}")
    for message in capture.messages[:6]:
        print("  sdk:", " ".join(message.split())[:200])
    if problems:
        for problem in problems:
            print(f"FAILED: {problem}", file=sys.stderr)
        return 1
    print("ok: the wire path degraded as documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
