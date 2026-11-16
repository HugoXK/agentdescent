"""Composition integrity: what a harness diff may not silently break (#949).

``invariants.py`` checks one artifact's diff against its own contract and
``safe_selfmod.py`` checks the source of a proposed change. Neither can see the
runtime shape of a *composed* harness: a plugin can still report ``active``
while the policy that mediated its tools no longer runs. This module is the
check between a plugin/harness diff and promotion.

A :class:`HarnessSnapshot` is the observable composition: the ordered guardrail
enforcement points, the permission/allow-rule state, the reachable action set
and the decision-path record for each enforced relationship. :class:`HarnessIntegrity`
compares a before/after pair and reports every broken relationship with the
state it observed. A changed action set is accepted only when the diff declares
exactly that change.

The check is deliberately a comparison, not another policy engine, sandbox or
formal verifier: it runs on the same offline data the caller already has.

    report = check_harness_integrity(before, after)
    report.ok, report.reason
    # "guardrail_order: policy @ 30 does not precede tool_mediation @ 10"
"""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DeclaredChanges",
    "HarnessIntegrity",
    "HarnessIntegrityReport",
    "HarnessSnapshot",
    "HarnessViolation",
    "check_harness_integrity",
]

#: The guardrail ordering a promoted harness must keep by default: a policy
#: decision has to run before the tool is mediated, or the plugin's tools are
#: reachable without the policy that was supposed to govern them.
DEFAULT_REQUIRED_ORDER: Tuple[Tuple[str, str], ...] = (
    ("policy", "tool_mediation"),
)


def _mapping(value: Any, name: str) -> Mapping:
    if not isinstance(value, MappingABC):
        raise TypeError(f"{name} must be a mapping")
    return value


def _strings(value: Any, name: str) -> Tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be a sequence of strings, not a bare string")
    try:
        items = tuple(value)
    except TypeError:
        raise TypeError(f"{name} must be a sequence of strings") from None
    return tuple(str(item) for item in items)


def _orders(value: Any) -> Mapping[str, int]:
    orders = {}
    for name, order in _mapping(value, "guardrails").items():
        key = _text(name, "guardrail name")
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
            raise ValueError(
                f"guardrail {key!r} order must be an int >= 0")
        orders[key] = order
    return orders


def _permissions(value: Any) -> Mapping[str, frozenset]:
    permissions = {}
    for principal, rules in _mapping(value, "permissions").items():
        key = _text(principal, "permission principal")
        permissions[key] = frozenset(_strings(rules, f"permissions[{key!r}]"))
    return permissions


def _records(value: Any) -> Mapping[str, str]:
    records = {}
    for relationship, record in _mapping(value, "decision_records").items():
        key = _text(relationship, "decision relationship")
        if not isinstance(record, str):
            raise TypeError(
                f"decision_records[{key!r}] must be a string record id")
        records[key] = record
    return records


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class HarnessSnapshot:
    """The observable runtime shape of one composed harness.

    ``guardrails`` maps an enforcement point to its position (lower runs first).
    ``permissions`` maps a principal to the actions its allow rules still grant.
    ``actions`` is the reachable action set. ``decision_records`` maps an
    enforced relationship -- ``policy->tool_mediation``, ``permission:<name>``
    -- to the id of the record that shows it was actually evaluated.
    """

    guardrails: Mapping[str, int]
    permissions: Mapping[str, frozenset]
    actions: frozenset
    decision_records: Mapping[str, str] = field(default_factory=dict)
    active_plugins: frozenset = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "guardrails", dict(_orders(self.guardrails)))
        object.__setattr__(self, "permissions", dict(_permissions(self.permissions)))
        object.__setattr__(self, "actions", frozenset(
            _strings(self.actions, "actions")))
        object.__setattr__(self, "decision_records",
                           dict(_records(self.decision_records)))
        object.__setattr__(self, "active_plugins", frozenset(
            _strings(self.active_plugins, "active_plugins")))


@dataclass(frozen=True)
class DeclaredChanges:
    """The actions a diff explicitly says it adds or removes.

    An undeclared delta is rejected: loading or unloading a plugin changes the
    reachable action set, so an implicit change is exactly the kind of silent
    reconfiguration this check exists to catch.
    """

    actions_added: frozenset = frozenset()
    actions_removed: frozenset = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions_added", frozenset(
            _strings(self.actions_added, "actions_added")))
        object.__setattr__(self, "actions_removed", frozenset(
            _strings(self.actions_removed, "actions_removed")))


@dataclass(frozen=True)
class HarnessViolation:
    """One broken relationship and the state the check observed."""

    relationship: str
    observed: str

    def __post_init__(self) -> None:
        _text(self.relationship, "relationship")
        if not isinstance(self.observed, str) or not self.observed.strip():
            raise ValueError("observed must be a non-empty string")

    def to_dict(self) -> dict:
        return {"relationship": self.relationship, "observed": self.observed}


@dataclass(frozen=True)
class HarnessIntegrityReport:
    """The verdict on one before/after snapshot pair."""

    ok: bool
    violations: Tuple[HarnessViolation, ...] = ()
    checked: Tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        return not self.ok

    @property
    def reason(self) -> str:
        if not self.violations:
            return "harness composition integrity holds"
        return "; ".join(
            f"{violation.relationship}: {violation.observed}"
            for violation in self.violations)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "rejected": self.rejected,
            "checked": list(self.checked),
            "violations": [violation.to_dict()
                           for violation in self.violations],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class HarnessIntegrity:
    """A before/after composition pair, ready to check before promotion."""

    before: HarnessSnapshot
    after: HarnessSnapshot
    declared: DeclaredChanges = field(default_factory=DeclaredChanges)
    required_order: Tuple[Tuple[str, str], ...] = DEFAULT_REQUIRED_ORDER

    def __post_init__(self) -> None:
        if not isinstance(self.before, HarnessSnapshot):
            raise TypeError("before must be a HarnessSnapshot")
        if not isinstance(self.after, HarnessSnapshot):
            raise TypeError("after must be a HarnessSnapshot")
        if not isinstance(self.declared, DeclaredChanges):
            raise TypeError("declared must be a DeclaredChanges")
        pairs = []
        if isinstance(self.required_order, (str, bytes)):
            raise TypeError("required_order must be a sequence of pairs")
        for pair in self.required_order:
            if (not isinstance(pair, Sequence) or isinstance(pair, (str, bytes))
                    or len(pair) != 2):
                raise TypeError("required_order entries must be name pairs")
            pairs.append((_text(pair[0], "required order name"),
                          _text(pair[1], "required order name")))
        object.__setattr__(self, "required_order", tuple(pairs))

    def check(self) -> HarnessIntegrityReport:
        """Compare the snapshots and report every broken relationship."""
        before, after = self.before, self.after
        violations = []
        checked = []

        # (a) Guardrails: the existing enforcement path survives, keeps its
        # relative order, and the required policy-before-tool relationship holds.
        for name in sorted(before.guardrails):
            if name not in after.guardrails:
                violations.append(HarnessViolation(
                    f"guardrail:{name}",
                    "missing from the enforcement path"))

        shared = sorted(set(before.guardrails) & set(after.guardrails),
                        key=lambda name: before.guardrails[name])
        before_order = list(shared)
        after_order = sorted(shared, key=lambda name: after.guardrails[name])
        # A tie is a broken order too: two enforcement points at the same
        # position cannot have a defined before/after relation.
        tied = any(after.guardrails[first] >= after.guardrails[second]
                   for first, second in zip(before_order, before_order[1:]))
        if before_order != after_order or tied:
            violations.append(HarnessViolation(
                "guardrail_order",
                f"before={before_order} after={after_order}"))

        enforced_records = set()
        for first, second in self.required_order:
            relationship = f"guardrail_order:{first}<{second}"
            checked.append(relationship)
            first_order = after.guardrails.get(first)
            second_order = after.guardrails.get(second)
            if first_order is None or second_order is None:
                missing = [name for name, order in (
                    (first, first_order), (second, second_order))
                    if order is None]
                violations.append(HarnessViolation(
                    relationship,
                    f"missing enforcement point(s) {missing}"))
            elif first_order >= second_order:
                violations.append(HarnessViolation(
                    relationship,
                    f"{first} @ {first_order} does not precede "
                    f"{second} @ {second_order}"))
            record_relationship = f"{first}->{second}"
            enforced_records.add(record_relationship)
            if not after.decision_records.get(record_relationship):
                violations.append(HarnessViolation(
                    f"decision_path:{record_relationship}",
                    "no decision record for the enforced relationship"))

        # (b) Permissions: every allow rule that applied before still applies.
        for principal in sorted(before.permissions):
            relationship = f"permission:{principal}"
            checked.append(relationship)
            enforced_records.add(relationship)
            rules = after.permissions.get(principal)
            if rules is None:
                violations.append(HarnessViolation(
                    relationship, "permission state was dropped"))
            else:
                dropped = sorted(before.permissions[principal] - rules)
                if dropped:
                    violations.append(HarnessViolation(
                        relationship,
                        f"allow rule(s) {dropped} no longer apply"))
            if not after.decision_records.get(relationship):
                violations.append(HarnessViolation(
                    f"decision_path:{relationship}",
                    "no decision record for the enforced relationship"))

        # (d) Every decision path that existed before still exists, including
        # relationships outside the ones the checks above enforce.
        for relationship in sorted(before.decision_records):
            if not before.decision_records[relationship]:
                continue
            if relationship in enforced_records:
                continue
            if not after.decision_records.get(relationship):
                violations.append(HarnessViolation(
                    f"decision_path:{relationship}",
                    "decision record no longer exists"))

        # (c) The action set may change only when the diff declares exactly it.
        checked.append("action_set")
        added = sorted(after.actions - before.actions)
        removed = sorted(before.actions - after.actions)
        if added or removed:
            declared_added = sorted(self.declared.actions_added)
            declared_removed = sorted(self.declared.actions_removed)
            if added != declared_added or removed != declared_removed:
                violations.append(HarnessViolation(
                    "action_set",
                    f"added={added} removed={removed}; diff declared "
                    f"added={declared_added} removed={declared_removed}"))

        return HarnessIntegrityReport(
            ok=not violations,
            violations=tuple(violations),
            checked=tuple(checked),
        )


def check_harness_integrity(
        before: HarnessSnapshot,
        after: HarnessSnapshot,
        *,
        declared: Optional[DeclaredChanges] = None,
        required_order: Sequence[Tuple[str, str]] = DEFAULT_REQUIRED_ORDER,
) -> HarnessIntegrityReport:
    """Compare two snapshots, optionally with the diff's declared changes."""
    return HarnessIntegrity(
        before=before,
        after=after,
        declared=declared or DeclaredChanges(),
        required_order=tuple(required_order),
    ).check()
