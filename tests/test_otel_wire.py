"""The real OTLP wire path, and the CI leg that runs it (#1083).

The offline suite stands a fake SDK in at ``otel_export._load_otel``: it pins the
wiring but cannot pin the SDK's own API or what happens when a collector is
unreachable. Two rows here cover exactly that gap:

1. with ``AGENTDESCENT_OTEL_WIRE=1`` (set by the ``otel-wire`` CI job) a real
   exporter is pointed at a closed port on 127.0.0.1 and the export must be
   logged and contained, never raised out of ``export_run``;
2. the workflow leg is asserted here, so deleting the only place the wire path
   runs fails a test instead of silently dropping the coverage.

The socket row is opt-in because the suite is offline by contract; the default
run never opens a socket.
"""

from __future__ import annotations

import logging
import os
import pathlib
import socket

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SMOKE_SCRIPT = ROOT / "scripts" / "otel_wire_smoke.py"


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.mark.skipif(
    os.environ.get("AGENTDESCENT_OTEL_WIRE") != "1",
    reason="real socket path; the otel-wire CI leg sets AGENTDESCENT_OTEL_WIRE=1",
)
def test_the_wire_path_degrades_instead_of_raising() -> None:
    """A refused connection must be logged, not raised out of ``export_run``."""
    from agentdescent import otel_export
    from agentdescent.otel_export import (
        DecisionSample,
        RoundSample,
        export_run,
        exporter_from_env,
    )

    try:
        otel_export._load_otel()
    except ImportError:
        pytest.skip("the [otel] extra is not installed")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])      # closed again by the context exit

    capture = _Capture()
    logger = logging.getLogger("opentelemetry")
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    try:
        exporter = exporter_from_env(
            {"OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{port}"})
        exported = export_run(
            exporter, run_id="wire-1",
            rounds=(RoundSample(1, reward=0.5, tokens=10, wallclock=1.0,
                                start=1.0, end=2.0),),
            decisions=(DecisionSample("skill", True, calls=1, prompt_tokens=5,
                                      wallclock=0.1, start=2.0, end=2.1),))
        flushed = exporter.force_flush(3000)
        exporter.shutdown()          # must not raise either
    finally:
        logger.removeHandler(capture)

    assert exported == 3            # one round span, one reward, one decision
    assert isinstance(flushed, bool)
    reported = "\n".join(capture.messages).lower()
    assert any(marker in reported for marker in (
        "connection refused", "connectionrefused", "failed to export",
        "max retries")), "the SDK never reported the refused connection"


def test_the_ci_leg_installs_the_extra_and_runs_the_smoke_script() -> None:
    """The wire path has exactly one place that runs it; this pins that place."""
    assert SMOKE_SCRIPT.is_file()

    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8")
    assert "otel-wire:" in workflow
    assert "otel]" in workflow                 # pip install -e ".[otel]"
    assert "scripts/otel_wire_smoke.py" in workflow
    assert "AGENTDESCENT_OTEL_WIRE=1" in workflow
