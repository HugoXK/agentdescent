"""A small OpenTelemetry-shaped trace model for RSI runs.

Metrics answer "how many"; traces answer **where the time and money went**.
The framework already has `rsi_metrics`, `manifest`, `diagnose`, `rsi_report`
and `chain_audit`; they are separate read models with no shared span tree. This
module is the common trace/event shape:

``run -> round -> rollout -> merge -> gate -> commit``

A span carries attributes (model, slot, artifact id, parent id, risk, verdict),
events (proposal, reject, adopt, rollback, human-defer), status and timestamps.
``to_otel()`` emits OTel-inspired dictionaries (not OTLP JSON: IDs are hex but
the kind/status/attribute encoding is simplified); ``to_prometheus()`` emits
counter/summary-style samples with escaped labels. No exporter is bundled, so
the module stays standard-library-only and testable with a fake clock.

    telemetry = RSITelemetry()
    with telemetry.span("run", kind="run") as run:
        with telemetry.span("round", kind="round", parent=run) as rnd:
            telemetry.event(rnd, "proposal", {"artifact_id": "a1"})
    report = telemetry.summary()
    otel = telemetry.to_otel()
"""

from __future__ import annotations

import math
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "MEMORY_OPERATIONS",
    "MEMORY_SPAN_SCHEMA",
    "MemoryAudit",
    "MemoryOperation",
    "ForgottenLesson",
    "LessonRegression",
    "TelemetryEvent",
    "TelemetrySpan",
    "TelemetryReport",
    "RSITelemetry",
    "memory_operation_from_decision",
    "memory_operation_from_evidence_card",
    "source_trace_ids_from_card",
    "validate_memory_span",
]

#: The four operations the shared memory model names (#947).
MEMORY_OPERATIONS: Tuple[str, ...] = ("read", "write", "update", "forget")
MEMORY_KIND_PREFIX = "memory."
_PROVENANCE_OPERATIONS = frozenset(("write", "update", "forget"))

# A span is telemetry, so it leaves the process. Drop credential-shaped keys and
# values at the boundary rather than trusting every caller to remember (#947).
#
# A key is a credential when a **whole component** of it names one, not when a
# substring does: matching `token` and `secret` as substrings also matched
# `tokens`, `max_tokens`, `token_count` and `secret_free`, deleting the counters
# a cost or budget span exists to record (#1070). The credential word is the
# head noun, so it drops in the last position; a word that is only ever a
# credential name drops in any position.
_CREDENTIAL_COMPONENTS = frozenset((
    "apikey", "accesskey", "privatekey", "secretkey", "clientsecret",
    "apitoken", "accesstoken", "authtoken", "refreshtoken", "bearertoken",
    "password", "passwd", "pwd", "credential", "credentials", "authorization",
    # A plural compound is still a credential in any position (`db_passwords`).
    "passwords", "passwds", "secretkeys", "apikeys", "privatekeys",
    "accesskeys", "clientsecrets",
))
_CREDENTIAL_NOUNS = frozenset(("token", "secret", "secrets"))
#: A credential written as one word (#1095): `PGPASSWORD` is libpq's password
#: variable and `s3secretkey` / `AWSSecretAccessKey` carry no separator, so a
#: single-component key is matched by whole-word suffix. `tokens` ends `okens`,
#: which is why the suffix has to be a whole credential word and not a stem.
_CREDENTIAL_WORDS = frozenset((
    "password", "passwd", "secret", "secretkey", "apikey", "privatekey",
    "accesskey", "clientsecret", "credential",
    "passwords", "passwds", "secrets", "secretkeys", "apikeys", "privatekeys",
    "accesskeys", "clientsecrets", "credentials",
))
#: Two components of one credential spelling (`api` + `key`).
_CREDENTIAL_PAIRS = frozenset((
    "apikey", "accesskey", "privatekey", "secretkey", "clientsecret",
    "apitoken", "accesstoken", "authtoken", "refreshtoken", "bearertoken",
))
_KEY_PARTS = re.compile(r"[_\-.\s]+")
_SECRET_VALUE = re.compile(
    r"(?:^|[\s\"'])(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{10,}|"
    r"gho_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"
    r"Bearer\s+[A-Za-z0-9._-]{10,})")


def _singular(word: str) -> Tuple[str, ...]:
    """``word`` and, when it ends in a plural ``s``, its singular (#1095)."""
    if len(word) > 1 and word.endswith("s"):
        return (word, word[:-1])
    return (word,)


def _pair_spells_a_credential(first: str, second: str) -> bool:
    """`api` + `keys`, `client` + `secrets`: one plural `s` is still the pair."""
    return any(left + right in _CREDENTIAL_PAIRS
               for left in _singular(first) for right in _singular(second))


def _is_secret_key(key: Any) -> bool:
    """True when a whole component of ``key`` names a credential (#1070).

    ``token_count`` and ``secret_free`` measure credentials, they are not one;
    ``client_secret`` and ``api_key`` are, in any spelling. A credential that is
    one word (`PGPASSWORD`, `s3secretkey`) has no component to see, so it is
    matched by whole-word suffix instead (#1095). Values are still filtered by
    :data:`_SECRET_VALUE` wherever they appear.
    """
    parts = [part for part in _KEY_PARTS.split(str(key).lower()) if part]
    if not parts:
        return False
    if any(part in _CREDENTIAL_COMPONENTS for part in parts):
        return True
    if parts[-1] in _CREDENTIAL_NOUNS:
        return True
    if len(parts) == 1 and any(parts[0].endswith(word)
                               for word in _CREDENTIAL_WORDS):
        return True
    return any(_pair_spells_a_credential(first, second)
               for first, second in zip(parts, parts[1:]))


def _safe_value(value: Any) -> Any:
    """JSON-safe and secret-free: unknown objects are dropped, not stringified."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(float(value)) else None
    if isinstance(value, str):
        return "[redacted]" if _SECRET_VALUE.search(value) else value
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item)
                for key, item in value.items() if not _is_secret_key(key)}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    return f"<{type(value).__name__}>"


def _safe_mapping(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return {str(key): _safe_value(item)
            for key, item in dict(value or {}).items()
            if not _is_secret_key(key)}


def _ids(value: Any, name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    out: List[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            raise ValueError(f"memory {name} must not contain an empty id")
        out.append(text)
    return tuple(dict.fromkeys(out))


@dataclass(frozen=True)
class MemoryOperation:
    """One memory read/write/update/forget and the evidence behind it (#947).

    ``provenance`` is ``source_trace_ids`` **and** ``evidence_hash``: the
    trajectory records that produced the lesson and the hash of the card that
    justified it. A write/update/forget without both is still emitted -- it is
    visible, and :class:`MemoryAudit` flags it -- rather than silently accepted.
    """

    operation: str
    lesson_id: str
    precondition: str = ""
    evidence_hash: str = ""
    source_trace_ids: Tuple[str, ...] = ()
    verifier: str = ""
    expected_effect: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    rolled_back: bool = False
    regressions: Tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        operation = str(self.operation)
        if operation not in MEMORY_OPERATIONS:
            raise ValueError(
                f"memory operation must be one of {list(MEMORY_OPERATIONS)}, "
                f"got {operation!r}")
        lesson_id = str(self.lesson_id or "").strip()
        if not lesson_id:
            raise ValueError("memory lesson_id is required")
        if not isinstance(self.rolled_back, bool):
            raise TypeError("memory rolled_back must be a bool")
        reason = str(self.reason or "")
        if operation == "forget" and not reason.strip():
            raise ValueError("memory.forget requires a non-empty reason")
        if self.rolled_back and not reason.strip():
            raise ValueError(
                "a rolled-back memory update requires a non-empty reason")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "lesson_id", lesson_id)
        object.__setattr__(self, "precondition", str(self.precondition or ""))
        object.__setattr__(self, "evidence_hash", str(self.evidence_hash or ""))
        object.__setattr__(self, "source_trace_ids",
                           _ids(self.source_trace_ids, "source_trace_ids"))
        object.__setattr__(self, "verifier", str(self.verifier or ""))
        object.__setattr__(self, "expected_effect",
                           _safe_mapping(self.expected_effect))
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "regressions", _ids(self.regressions,
                                                     "regressions"))
        object.__setattr__(self, "attributes", _safe_mapping(self.attributes))

    @property
    def has_provenance(self) -> bool:
        return bool(self.source_trace_ids) and bool(self.evidence_hash.strip())

    def to_span_attributes(self) -> Dict[str, Any]:
        attributes = dict(self.attributes)
        attributes.update({
            "memory.operation": self.operation,
            "memory.lesson_id": self.lesson_id,
            "memory.precondition": self.precondition,
            "memory.evidence_hash": self.evidence_hash,
            "memory.source_trace_ids": list(self.source_trace_ids),
            "memory.verifier": self.verifier,
            "memory.expected_effect": dict(self.expected_effect),
            "memory.provenance": self.has_provenance,
            "memory.reason": self.reason,
            "memory.rolled_back": self.rolled_back,
            "memory.regressions": list(self.regressions),
        })
        # The fields above are immutable, so __post_init__ never saw them and
        # _SECRET_VALUE never ran: a lesson id, precondition or verifier could
        # carry a credential straight out of the process (#1063).
        return _safe_mapping(attributes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "operation": self.operation,
            "lesson_id": self.lesson_id,
            "precondition": self.precondition,
            "evidence_hash": self.evidence_hash,
            "source_trace_ids": list(self.source_trace_ids),
            "verifier": self.verifier,
            "expected_effect": dict(self.expected_effect),
            "reason": self.reason,
            "rolled_back": self.rolled_back,
            "regressions": list(self.regressions),
            "provenance": self.has_provenance,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MemoryOperation":
        errors = validate_memory_span(payload)
        if errors:
            raise ValueError("invalid memory span: " + "; ".join(errors))
        return cls(
            operation=payload["operation"],
            lesson_id=payload["lesson_id"],
            precondition=payload.get("precondition", ""),
            evidence_hash=payload.get("evidence_hash", ""),
            source_trace_ids=tuple(payload.get("source_trace_ids") or ()),
            verifier=payload.get("verifier", ""),
            expected_effect=dict(payload.get("expected_effect") or {}),
            reason=payload.get("reason", ""),
            rolled_back=bool(payload.get("rolled_back", False)),
            regressions=tuple(payload.get("regressions") or ()),
            attributes=dict(payload.get("attributes") or {}))


#: Minimal Draft 2020-12 schema for one emitted memory span. No validator
#: dependency: :func:`validate_memory_span` is the stdlib check used in tests.
MEMORY_SPAN_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://agentdescent.dev/schemas/memory-span-v1.json",
    "title": "AgentDescent memory operation span v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "operation", "lesson_id", "precondition",
        "evidence_hash", "source_trace_ids", "verifier", "expected_effect",
        "reason", "rolled_back", "regressions", "provenance", "attributes",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "operation": {"enum": list(MEMORY_OPERATIONS)},
        "lesson_id": {"type": "string", "minLength": 1},
        "precondition": {"type": "string"},
        "evidence_hash": {"type": "string"},
        "source_trace_ids": {
            "type": "array", "items": {"type": "string", "minLength": 1}},
        "verifier": {"type": "string"},
        "expected_effect": {"type": "object"},
        "reason": {"type": "string"},
        "rolled_back": {"type": "boolean"},
        "regressions": {
            "type": "array", "items": {"type": "string", "minLength": 1}},
        "provenance": {"type": "boolean"},
        "attributes": {"type": "object"},
    },
}


def validate_memory_span(payload: Any) -> List[str]:
    """Refusal lines for one span payload; empty means it satisfies v1."""
    if not isinstance(payload, Mapping):
        return ["a memory span must be a JSON object"]
    errors: List[str] = []
    known = set(MEMORY_SPAN_SCHEMA["properties"])
    errors.extend(f"{name}: unknown field" for name in payload if name not in known)
    version = payload.get("schema_version")
    if isinstance(version, bool) or version != 1:
        errors.append(f"schema_version: {version!r}, expected 1")
    operation = payload.get("operation")
    if operation not in MEMORY_OPERATIONS:
        errors.append(
            f"operation: {operation!r} is not one of {list(MEMORY_OPERATIONS)}")
    lesson_id = payload.get("lesson_id")
    if not isinstance(lesson_id, str) or not lesson_id.strip():
        errors.append("lesson_id: must be a non-empty string")
    for name in ("precondition", "evidence_hash", "verifier", "reason"):
        if name in payload and not isinstance(payload[name], str):
            errors.append(f"{name}: must be a string")
    for name in ("source_trace_ids", "regressions"):
        values = payload.get(name, [])
        if not isinstance(values, (list, tuple)):
            errors.append(f"{name}: must be an array of strings")
        elif any(not isinstance(value, str) or not value.strip()
                 for value in values):
            errors.append(f"{name}: every id must be a non-empty string")
    rolled_back = payload.get("rolled_back", False)
    if not isinstance(rolled_back, bool):
        errors.append("rolled_back: must be a boolean")
    provenance = payload.get("provenance")
    if provenance is not None and not isinstance(provenance, bool):
        errors.append("provenance: must be a boolean")
    for name in ("expected_effect", "attributes"):
        if not isinstance(payload.get(name, {}), Mapping):
            errors.append(f"{name}: must be an object")
    reason = payload.get("reason", "")
    if operation == "forget" and not str(reason).strip():
        errors.append("reason: memory.forget requires a non-empty reason")
    if rolled_back is True and not str(reason).strip():
        errors.append("reason: a rolled-back update requires a non-empty reason")
    return errors


def source_trace_ids_from_card(card: Any) -> Tuple[str, ...]:
    """The persisted rollout trace ids on an ``EvidenceCard`` (#947)."""
    traces = getattr(card, "trace_ids", ()) or ()
    if isinstance(traces, str):
        traces = (traces,)
    return tuple(str(trace) for trace in traces if str(trace).strip())


def memory_operation_from_evidence_card(
        card: Any, *, lesson_id: str, operation: str = "write",
        **kwargs: Any) -> MemoryOperation:
    """Build an operation from ``EvidenceCard.trace_ids``/``trajectory_refs``."""
    refs: List[str] = []
    for ref in getattr(card, "trajectory_refs", ()) or ():
        value = getattr(ref, "id", None) or getattr(ref, "run_id", None) or ref
        text = str(value).strip()
        if text:
            refs.append(text)
    attributes = dict(kwargs.pop("attributes", {}) or {})
    if refs:
        attributes["evidence.trajectory_refs"] = refs
    return MemoryOperation(
        operation, lesson_id,
        source_trace_ids=source_trace_ids_from_card(card),
        attributes=attributes, **kwargs)


def memory_operation_from_decision(
        record: Any, *, operation: str = "write",
        **kwargs: Any) -> MemoryOperation:
    """Build an operation from a ``DecisionRecord``'s evidence (#947)."""
    evidence = dict(getattr(record, "evidence", {}) or {})
    lesson_id = str(getattr(record, "artifact_id", "")
                    or getattr(record, "diff_id", "") or "")
    traces = evidence.get("trace_ids") or evidence.get("source_trace_ids") or ()
    if isinstance(traces, str):
        traces = (traces,)
    fields: Dict[str, Any] = {
        "precondition": evidence.get("precondition", ""),
        "evidence_hash": evidence.get(
            "evidence_card_hash", evidence.get("evidence_hash", "")),
        "source_trace_ids": tuple(str(trace) for trace in traces),
        "verifier": evidence.get("verifier", ""),
        "expected_effect": evidence.get("expected_effect") or {},
        "reason": kwargs.pop("reason", getattr(record, "detail", "") or ""),
        "rolled_back": kwargs.pop("rolled_back", False),
        "regressions": kwargs.pop("regressions", ()),
    }
    fields.update(kwargs)
    return MemoryOperation(operation, lesson_id, **fields)


@dataclass(frozen=True)
class LessonRegression:
    """A regression the audit can name a lesson (and tasks) for."""

    lesson_id: str
    task_ids: Tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"lesson_id": self.lesson_id, "task_ids": list(self.task_ids),
                "reason": self.reason}


@dataclass(frozen=True)
class ForgottenLesson:
    """A forgotten or rolled-back lesson and the reason it was removed."""

    lesson_id: str
    reason: str = ""
    rolled_back: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"lesson_id": self.lesson_id, "reason": self.reason,
                "rolled_back": self.rolled_back}


@dataclass(frozen=True)
class MemoryAudit:
    """The memory block of a telemetry report: counts, provenance, regressions."""

    reads: int = 0
    writes: int = 0
    updates: int = 0
    forgets: int = 0
    lessons_without_provenance: Tuple[str, ...] = ()
    forgotten: Tuple[ForgottenLesson, ...] = ()
    regressions: Tuple[LessonRegression, ...] = ()
    source_trace_ids: Tuple[str, ...] = ()
    detail: str = ""

    @classmethod
    def from_spans(cls, spans: Any) -> "MemoryAudit":
        counts = {operation: 0 for operation in MEMORY_OPERATIONS}
        traces = set()
        unprovenanced = set()
        forgotten: Dict[str, ForgottenLesson] = {}
        regressions: List[LessonRegression] = []
        for span in spans:
            kind = str(getattr(span, "kind", ""))
            if not kind.startswith(MEMORY_KIND_PREFIX):
                continue
            attributes = dict(getattr(span, "attributes", {}) or {})
            operation = str(attributes.get("memory.operation")
                            or kind[len(MEMORY_KIND_PREFIX):])
            if operation not in counts:
                continue
            counts[operation] += 1
            for trace in attributes.get("memory.source_trace_ids") or ():
                text = str(trace).strip()
                if text:
                    traces.add(text)
            lesson_id = str(attributes.get("memory.lesson_id") or "").strip()
            if (operation in _PROVENANCE_OPERATIONS and lesson_id
                    and not attributes.get("memory.provenance")):
                unprovenanced.add(lesson_id)
            reason = str(attributes.get("memory.reason") or "")
            rolled_back = bool(attributes.get("memory.rolled_back"))
            if lesson_id and (operation == "forget"
                              or (operation == "update" and rolled_back)):
                forgotten.setdefault(lesson_id, ForgottenLesson(
                    lesson_id, reason, rolled_back or operation == "forget"))
            task_ids = tuple(sorted(
                str(task) for task in attributes.get("memory.regressions") or ()
                if str(task).strip()))
            if lesson_id and task_ids:
                regressions.append(
                    LessonRegression(lesson_id, task_ids, reason))
        unique = []
        seen = set()
        for row in regressions:
            key = (row.lesson_id, row.task_ids)
            if key not in seen:
                seen.add(key)
                unique.append(row)
        return cls(
            reads=counts["read"], writes=counts["write"],
            updates=counts["update"], forgets=counts["forget"],
            lessons_without_provenance=tuple(sorted(unprovenanced)),
            forgotten=tuple(forgotten[key] for key in sorted(forgotten)),
            regressions=tuple(unique),
            source_trace_ids=tuple(sorted(traces)),
            detail=(f"{counts['read']} read(s), {counts['write']} write(s), "
                    f"{counts['update']} update(s), {counts['forget']} "
                    f"forget(s); {len(unprovenanced)} lesson(s) without "
                    f"provenance, {len(forgotten)} forgotten, "
                    f"{len(unique)} regression(s)"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reads": self.reads,
            "writes": self.writes,
            "updates": self.updates,
            "forgets": self.forgets,
            "lessons_without_provenance": list(self.lessons_without_provenance),
            "forgotten": [row.to_dict() for row in self.forgotten],
            "regressions": [row.to_dict() for row in self.regressions],
            "source_trace_ids": list(self.source_trace_ids),
            "detail": self.detail,
        }


@dataclass
class TelemetryEvent:
    """One point-in-time event inside a span."""

    name: str
    timestamp: float
    attributes: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("TelemetryEvent.name must be non-empty")
        if not math.isfinite(float(self.timestamp)):
            raise ValueError("TelemetryEvent.timestamp must be finite")


@dataclass
class TelemetrySpan:
    """One span in the RSI trace tree."""

    trace_id: str
    span_id: str
    name: str
    kind: str
    start: float
    parent_id: Optional[str] = None
    end: Optional[float] = None
    status: str = "unset"
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[TelemetryEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("TelemetrySpan.name must be non-empty")
        if not self.kind:
            raise ValueError("TelemetrySpan.kind must be non-empty")
        if not math.isfinite(float(self.start)):
            raise ValueError("TelemetrySpan.start must be finite")
        # The constructor is an entry point: a caller can build a span directly
        # and a span leaves the process (#1063).
        self.attributes = _safe_mapping(self.attributes)

    @property
    def duration(self) -> Optional[float]:
        if self.end is None:
            return None
        return max(0.0, float(self.end) - float(self.start))

    @property
    def finished(self) -> bool:
        return self.end is not None

    def set_attribute(self, key: str, value: Any) -> "TelemetrySpan":
        key = str(key)
        # Drop by key and redact by value here, as the span export does (#1063).
        if not _is_secret_key(key):
            self.attributes[key] = _safe_value(value)
        return self

    def add_event(self, name: str, attributes: Optional[Mapping[str, Any]] = None,
                  *, timestamp: Optional[float] = None) -> TelemetryEvent:
        event = TelemetryEvent(name, time.time() if timestamp is None else timestamp,
                               _safe_mapping(attributes))
        self.events.append(event)
        return event

    def finish(self, status: str = "ok", *, timestamp: Optional[float] = None) -> "TelemetrySpan":
        if status not in ("ok", "error", "cancelled", "unset"):
            raise ValueError("status must be ok, error, cancelled or unset")
        if self.end is not None:
            raise ValueError("span is already finished")
        end = time.time() if timestamp is None else float(timestamp)
        if not math.isfinite(end):
            raise ValueError("end timestamp must be finite")
        if end < self.start:
            raise ValueError("end timestamp must be >= start")
        self.status = status
        self.end = end
        return self


@dataclass(frozen=True)
class TelemetryReport:
    """A read model over a completed (or in-flight) trace set."""

    spans: int
    traces: int
    roots: int
    errors: int
    kinds: Dict[str, int]
    wall_time: float
    span_time: float
    detail: str = ""
    #: Memory reads/writes/updates/forgets, missing provenance and regressions
    #: (#947). ``None`` only on a report built without spans.
    memory: Optional[MemoryAudit] = None


class RSITelemetry:
    """Create spans and export them in OTel/Prometheus-friendly shapes."""

    def __init__(self, clock: Optional[Callable[[], float]] = None,
                 id_factory: Optional[Callable[[str], str]] = None) -> None:
        self.clock = clock or time.time
        self.id_factory = id_factory or (
            lambda kind: secrets.token_hex(16 if kind == "trace" else 8))
        self._spans: List[TelemetrySpan] = []

    @property
    def spans(self) -> Tuple[TelemetrySpan, ...]:
        return tuple(self._spans)

    def start_span(self, name: str, kind: str = "span", *,
                   parent: Optional[TelemetrySpan] = None,
                   attributes: Optional[Mapping[str, Any]] = None,
                   trace_id: Optional[str] = None) -> TelemetrySpan:
        if parent is not None:
            if parent not in self._spans:
                raise ValueError("parent span belongs to a different RSITelemetry")
            if trace_id is not None and trace_id != parent.trace_id:
                raise ValueError("trace_id conflicts with the parent span")
            trace_id = parent.trace_id
        if trace_id is None:
            trace_id = self.id_factory("trace")
        span = TelemetrySpan(
            trace_id=trace_id, span_id=self.id_factory("span"),
            name=name, kind=kind, start=float(self.clock()),
            parent_id=parent.span_id if parent is not None else None,
            attributes=_safe_mapping(attributes))
        self._spans.append(span)
        return span

    def end_span(self, span: TelemetrySpan, status: str = "ok") -> TelemetrySpan:
        return span.finish(status, timestamp=float(self.clock()))

    def event(self, span: TelemetrySpan, name: str,
              attributes: Optional[Mapping[str, Any]] = None) -> TelemetryEvent:
        return span.add_event(name, attributes, timestamp=float(self.clock()))

    def span(self, name: str, kind: str = "span", *,
             parent: Optional[TelemetrySpan] = None,
             attributes: Optional[Mapping[str, Any]] = None) -> "_SpanContext":
        return _SpanContext(self, name, kind, parent, attributes)

    def memory_operation(self, operation: str, *, lesson_id: str,
                         parent: Optional[TelemetrySpan] = None,
                         status: str = "ok",
                         **fields: Any) -> TelemetrySpan:
        """Emit one ``memory.<operation>`` span with evidence-linked provenance."""
        op = MemoryOperation(operation, lesson_id, **fields)
        span = self.start_span(
            f"memory.{op.operation}", kind=f"memory.{op.operation}",
            parent=parent, attributes=op.to_span_attributes())
        self.end_span(span, status)
        return span

    def summary(self) -> TelemetryReport:
        traces = {span.trace_id for span in self._spans}
        kinds: Dict[str, int] = {}
        span_time = 0.0
        wall_time = 0.0
        for span in self._spans:
            kinds[span.kind] = kinds.get(span.kind, 0) + 1
            if span.duration is not None:
                span_time += span.duration
                if span.parent_id is None:
                    wall_time += span.duration
        roots = sum(1 for span in self._spans if span.parent_id is None)
        errors = sum(1 for span in self._spans if span.status == "error")
        return TelemetryReport(
            spans=len(self._spans), traces=len(traces), roots=roots,
            errors=errors, kinds=dict(sorted(kinds.items())),
            wall_time=wall_time, span_time=span_time,
            detail=(f"{len(self._spans)} span(s) over {len(traces)} trace(s), "
                    f"{errors} error(s), wall={wall_time:.6g}s, "
                    f"span-time={span_time:.6g}s"),
            memory=MemoryAudit.from_spans(self._spans))

    def to_otel(self) -> List[Dict[str, Any]]:
        """OTel-GenAI-shaped dictionaries (no exporter dependency)."""
        out = []
        for span in self._spans:
            out.append({
                "traceId": span.trace_id,
                "spanId": span.span_id,
                "parentSpanId": span.parent_id,
                "name": span.name,
                "kind": span.kind,
                "startTimeUnixNano": int(float(span.start) * 1_000_000_000),
                "endTimeUnixNano": (None if span.end is None
                                    else int(float(span.end) * 1_000_000_000)),
                "attributes": {**dict(span.attributes), "rsi.span.kind": span.kind},
                "events": [
                    {"name": event.name,
                     "timeUnixNano": int(float(event.timestamp) * 1_000_000_000),
                     "attributes": dict(event.attributes)}
                    for event in span.events
                ],
                "status": span.status,
            })
        return out

    @staticmethod
    def _label(value: str) -> str:
        return (str(value).replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n"))

    def to_prometheus(self) -> List[str]:
        """Counter-style samples with escaped labels; no client library."""
        report = self.summary()
        lines = [
            "# TYPE rsi_traces_total counter",
            f"rsi_traces_total {report.traces}",
            "# TYPE rsi_span_errors_total counter",
            f"rsi_span_errors_total {report.errors}",
            "# TYPE rsi_span_seconds summary",
            f"rsi_span_seconds_sum {report.span_time:.6f}",
            f"rsi_span_seconds_count {report.spans}",
            "# TYPE rsi_spans_total counter",
        ]
        for kind, count in report.kinds.items():
            lines.append(f'rsi_spans_total{{kind="{self._label(kind)}"}} {count}')
        return lines


class _SpanContext:
    def __init__(self, telemetry: RSITelemetry, name: str, kind: str,
                 parent: Optional[TelemetrySpan],
                 attributes: Optional[Mapping[str, Any]]) -> None:
        self.telemetry = telemetry
        self.span = telemetry.start_span(name, kind, parent=parent,
                                         attributes=attributes)

    def __enter__(self) -> TelemetrySpan:
        return self.span

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.telemetry.end_span(self.span, "ok")
        else:
            cancelled = not issubclass(exc_type, Exception)
            self.telemetry.end_span(self.span, "cancelled" if cancelled else "error")
            if not cancelled:
                self.telemetry.event(self.span, "exception",
                                     {"type": exc_type.__name__,
                                      "message": _safe_value(str(exc))})
        return False
