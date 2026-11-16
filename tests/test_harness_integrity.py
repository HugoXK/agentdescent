"""A plugin diff may not silently break the harness it is composed into (#949).

The plugin can still report "active" while the policy that used to mediate its
tools no longer evaluates anything. These fixtures pin the four relationships a
promotion must re-check after a diff: guardrail order, permission state, the
action set and the decision path.
"""

from __future__ import annotations

from dataclasses import replace

from agentdescent.governed_harness import govern_harness_change
from agentdescent.harness_integrity import (
    DeclaredChanges,
    HarnessIntegrity,
    HarnessSnapshot,
    check_harness_integrity,
)
from agentdescent.proofs import ProofInvariant, ProofRunner
from agentdescent.safe_selfmod import ModificationSpec, SafeSelfModifier


def _base(**overrides):
    values = dict(
        guardrails={
            "input_filter": 0, "policy": 10,
            "tool_mediation": 20, "output_filter": 30,
        },
        permissions={
            "assistant": frozenset({"files.read", "tools.invoke"}),
            "operator": frozenset({"files.read", "files.write"}),
        },
        actions=frozenset({"files.read", "files.write", "tools.invoke"}),
        decision_records={
            "policy->tool_mediation": "rec-policy-tool",
            "permission:assistant": "rec-assistant",
            "permission:operator": "rec-operator",
        },
        active_plugins=frozenset({"governance"}),
    )
    values.update(overrides)
    return HarnessSnapshot(**values)


def test_a_benign_plugin_change_passes():
    before = _base()
    after = replace(
        before,
        active_plugins=frozenset({"governance", "plugin-observability"}),
        decision_records={
            **before.decision_records,
            "policy->tool_mediation": "rec-policy-tool-2",
        },
    )
    report = check_harness_integrity(before, after)
    assert report.ok
    assert report.violations == ()
    assert "action_set" in report.checked
    assert "guardrail_order:policy<tool_mediation" in report.checked


def test_reordered_guardrails_are_rejected():
    before = _base()
    after = replace(before, guardrails={
        "input_filter": 0, "policy": 30,
        "tool_mediation": 10, "output_filter": 40,
    })
    report = check_harness_integrity(before, after)
    assert not report.ok
    assert any(v.relationship.startswith("guardrail_order")
               for v in report.violations)
    assert "policy" in report.reason and "tool_mediation" in report.reason


def test_a_guardrail_tie_is_rejected_as_an_undefined_order():
    before = _base()
    after = replace(before, guardrails={
        "input_filter": 0, "policy": 20,
        "tool_mediation": 20, "output_filter": 30,
    })
    report = check_harness_integrity(before, after)
    assert not report.ok
    assert any(v.relationship.startswith("guardrail_order")
               for v in report.violations)


def test_dropped_permission_state_is_rejected():
    before = _base()
    after = replace(before, permissions={
        "assistant": frozenset({"files.read"}),
        "operator": before.permissions["operator"],
    })
    report = check_harness_integrity(before, after)
    assert not report.ok
    violation = next(v for v in report.violations
                     if v.relationship == "permission:assistant")
    assert "tools.invoke" in violation.observed
    assert "permission:assistant" in report.reason


def test_action_set_change_needs_an_explicit_declaration():
    before = _base()
    after = replace(before, actions=before.actions | {"shell.exec"})

    rejected = check_harness_integrity(before, after)
    assert not rejected.ok
    assert any(v.relationship == "action_set" for v in rejected.violations)
    assert "shell.exec" in rejected.reason

    declared = DeclaredChanges(actions_added=frozenset({"shell.exec"}))
    assert check_harness_integrity(before, after, declared=declared).ok


def test_plugin_active_but_policy_stopped_evaluating_fixture():
    before = _base()
    after = replace(
        before,
        guardrails={name: order for name, order in before.guardrails.items()
                    if name != "policy"},
        decision_records={name: record
                          for name, record in before.decision_records.items()
                          if not name.startswith("policy->")},
    )
    report = check_harness_integrity(before, after)

    assert after.active_plugins == before.active_plugins
    assert not report.ok
    assert any(v.relationship == "guardrail:policy"
               for v in report.violations)
    assert any(v.relationship == "decision_path:policy->tool_mediation"
               for v in report.violations)
    assert "policy" in report.reason


def test_governed_change_rejects_before_proof_and_promotion():
    before = _base()
    after = replace(before, guardrails={
        "input_filter": 0, "policy": 30,
        "tool_mediation": 10, "output_filter": 40,
    })
    calls = []

    def must_not_run(_modification):
        calls.append(1)
        return True

    report = govern_harness_change(
        "harness-1",
        ModificationSpec("m1", "def f(x):\n    return x\n", "harness/f.py",
                         (), 0.0),
        {"t0": 0.5}, {"t0": 0.9},
        gate=SafeSelfModifier(set()),
        prover=ProofRunner([ProofInvariant("always", must_not_run)],
                           issuer="test"),
        integrity=HarnessIntegrity(before, after),
        contaminated=False,
    )

    assert report.decision.action == "reject"
    assert not report.promoted
    assert report.evidence is None
    assert calls == []
    assert report.integrity is not None and not report.integrity.ok
    assert "guardrail_order" in report.detail
