"""Memory operations are telemetry, and the audit names what is missing (#947)."""

import pytest

from agentdescent.continual_meta import ContinualMetaLearner
from agentdescent.decisions import DecisionRecord
from agentdescent.experience import (
    ExperienceEngine,
    ExperienceRecord,
    ExperienceStore,
)
from agentdescent.rsi_telemetry import (
    MEMORY_OPERATIONS,
    MEMORY_SPAN_SCHEMA,
    MemoryOperation,
    RSITelemetry,
    memory_operation_from_decision,
    memory_operation_from_evidence_card,
    source_trace_ids_from_card,
    validate_memory_span,
)


def _ids():
    state = {"trace": 0, "span": 0}

    def make(kind):
        state[kind] += 1
        return f"{kind}-{state[kind]}"

    return make


def _telemetry():
    ticks = iter(range(10_000))
    return RSITelemetry(clock=lambda: float(next(ticks)), id_factory=_ids())


def _learner(*, learning_rate=0.5, min_gain=0.0):
    return ContinualMetaLearner(
        ["a", "b"], dim=1, learning_rate=learning_rate, l2=0.0,
        replay_size=16, min_gain=min_gain, seed=0)


def _record(run_id, *, feature=1.0, rewards=None, metadata=None):
    return ExperienceRecord(
        run_id, (feature,), rewards or {"a": 1.0, "b": 0.0},
        artifact_id=f"artifact-{run_id}", metadata=metadata or {})


def _provenance():
    return {
        "lesson_id": "lesson-1",
        "precondition": "task needs a worked example",
        "evidence_hash": "abc123",
        "source_trace_ids": ["trace-a", "trace-b"],
        "verifier": "unit",
        "expected_effect": {"gain": 0.1},
    }


def test_run_emits_memory_spans_and_report_counts_source_traces():
    telemetry = _telemetry()
    engine = ExperienceEngine(
        _learner(), ExperienceStore(), require_anchors=False,
        telemetry=telemetry)
    rows = [_record("r1", metadata=_provenance()),
            _record("r2", metadata=_provenance())]
    for row in rows:
        engine.ingest(row)
    hits = engine.recall((1.0,), k=2)
    update = engine.update(validation=rows, anchors=[])

    assert update.accepted
    report = telemetry.summary()
    assert report.memory is not None
    assert report.memory.reads == len(hits) == 2
    assert report.memory.writes == 2
    assert report.memory.updates == 1
    assert report.memory.forgets == 0
    assert set(report.memory.source_trace_ids) >= {"trace-a", "trace-b"}
    assert report.memory.lessons_without_provenance == ()
    assert engine.report().memory == report.memory

    names = [span.name for span in telemetry.spans]
    assert {"memory.read", "memory.write", "memory.update"} <= set(names)
    write = next(span for span in telemetry.spans
                 if span.name == "memory.write")
    assert write.attributes["memory.lesson_id"] == "lesson-1"
    assert write.attributes["memory.source_trace_ids"] == [
        "trace-a", "trace-b"]
    assert write.attributes["memory.provenance"] is True


def test_lesson_without_provenance_is_flagged_not_silently_accepted():
    telemetry = _telemetry()
    engine = ExperienceEngine(
        _learner(), ExperienceStore(), require_anchors=False,
        telemetry=telemetry)
    engine.ingest(_record("bare", metadata={"lesson_id": "lesson-bare"}))

    audit = telemetry.summary().memory
    assert audit.writes == 1
    assert audit.lessons_without_provenance == ("lesson-bare",)
    write = next(span for span in telemetry.spans
                 if span.name == "memory.write")
    assert write.attributes["memory.provenance"] is False

    assert memory_operation_from_decision(DecisionRecord(
        record_id="r", kind="adoption", artifact_id="lesson-bare",
        diff_id="d1", accepted=True)).has_provenance is False


def test_forgotten_and_rolled_back_lesson_appears_with_a_reason():
    telemetry = _telemetry()
    learner = _learner(learning_rate=1.0, min_gain=-1.0)
    engine = ExperienceEngine(
        learner, ExperienceStore(), telemetry=telemetry)
    validation = [
        _record(f"v{i}", rewards={"a": 0.0, "b": 1.0},
                metadata=_provenance())
        for i in range(3)
    ]
    for row in validation:
        engine.ingest(row)
    anchor = _record("anchor", rewards={"a": 1.0, "b": 0.0},
                     metadata=_provenance())
    update = engine.update(validation=validation, anchors=[anchor])

    assert update.rolled_back
    audit = telemetry.summary().memory
    assert audit.updates == 1
    assert audit.forgets == 1
    assert [row.lesson_id for row in audit.forgotten] == ["lesson-1"]
    assert audit.forgotten[0].rolled_back is True
    assert "forgetting guard" in audit.forgotten[0].reason

    forget = next(span for span in telemetry.spans
                  if span.name == "memory.forget")
    assert forget.attributes["memory.reason"] == update.reason


def test_lesson_attributable_regressions_are_in_the_audit():
    telemetry = _telemetry()
    telemetry.memory_operation(
        "update", lesson_id="lesson-regressing", precondition="p",
        evidence_hash="h", source_trace_ids=("trace-r",), verifier="probe",
        expected_effect={"gain": 0.1}, regressions=("task-9", "task-3"))

    audit = telemetry.summary().memory
    assert audit.updates == 1
    assert len(audit.regressions) == 1
    assert audit.regressions[0].lesson_id == "lesson-regressing"
    assert audit.regressions[0].task_ids == ("task-3", "task-9")


def test_memory_span_schema_round_trips_and_drops_secrets():
    operation = MemoryOperation(
        "write", "lesson-1", precondition="p", evidence_hash="h",
        source_trace_ids=("t1",), verifier="v",
        expected_effect={"gain": 0.2},
        attributes={"api_key": "sk-live-secret", "label": "kept"})
    payload = operation.to_dict()
    assert validate_memory_span(payload) == []
    assert payload["source_trace_ids"] == ["t1"]
    assert "api_key" not in payload["attributes"]
    assert payload["attributes"] == {"label": "kept"}
    assert MemoryOperation.from_dict(payload) == operation
    assert MEMORY_SPAN_SCHEMA["properties"]["operation"]["enum"] == list(
        MEMORY_OPERATIONS)

    telemetry = _telemetry()
    span = telemetry.memory_operation(
        "write", lesson_id="lesson-1", evidence_hash="h",
        source_trace_ids=("t1",),
        attributes={"access_token": "ghp_should_not_survive", "label": "kept"})
    assert "sk-live-secret" not in str(payload)
    assert "ghp_should_not_survive" not in str(span.attributes)

    with pytest.raises(ValueError):
        MemoryOperation("forget", "lesson-1")  # a forget needs a reason
    with pytest.raises(ValueError):
        MemoryOperation("write", "")
    errors = validate_memory_span(dict(payload, operation="sideways"))
    assert any("operation" in line for line in errors)
    errors = validate_memory_span(dict(payload, source_trace_ids=[""]))
    assert any("source_trace_ids" in line for line in errors)


def test_memory_operation_reuses_decision_and_evidence_card_shapes():
    decision = DecisionRecord(
        record_id="r", kind="adoption", artifact_id="lesson-1",
        diff_id="d1", accepted=True, detail="committed",
        evidence={"trace_ids": ["trace-1"], "evidence_card_hash": "abc",
                  "verifier": "falsification-probes:v1",
                  "precondition": "base v1",
                  "expected_effect": {"base": 0.2, "candidate": 0.4}})
    operation = memory_operation_from_decision(decision)
    assert operation.lesson_id == "lesson-1"
    assert operation.source_trace_ids == ("trace-1",)
    assert operation.evidence_hash == "abc"
    assert operation.verifier == "falsification-probes:v1"
    assert operation.expected_effect == {"base": 0.2, "candidate": 0.4}

    class _Ref:
        id = "task-1"

    class _Card:
        trace_ids = ("trace-1",)
        trajectory_refs = [_Ref()]

    assert source_trace_ids_from_card(_Card()) == ("trace-1",)
    from_card = memory_operation_from_evidence_card(_Card(), lesson_id="L")
    assert from_card.source_trace_ids == ("trace-1",)
    assert from_card.attributes["evidence.trajectory_refs"] == ["task-1"]
