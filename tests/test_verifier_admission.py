"""A verifier's admission rate must be measured on both strata, not just the good one."""

from __future__ import annotations

from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from agentdescent.admission import AdmissionReport
from agentdescent.policies import AcceptDecision, MergeContext
from agentdescent.promotion import (PromotionAction, PromotionRequest,
                                    PromotionRules, promote)
from agentdescent.verifier_curriculum import VerifierAgreement
from agentdescent.verifier_ensemble import EnsembleReport

ACCEPT = lambda ctx: AcceptDecision(True)
REJECT = lambda ctx: AcceptDecision(False, "inner-says-no")


def _ctx(base, cand):
    return MergeContext(artifact=SimpleNamespace(name=base),
                        candidate=SimpleNamespace(name=cand),
                        cards=[], base_counts=(0.5, 0.5), cand_counts=(0.9, 0.1))


def _gate(verifier, oracle, inner, tasks=(0,)):
    score = lambda table: lambda artifact, task: table[artifact.name][task]
    return VerifierAgreement(tuple(tasks), score(verifier), score(oracle),
                             sample_rate=1.0, rejected_sample_rate=1.0,
                             inner=inner)


def _pairs(prefix, count, base_score, cand_score):
    """``count`` distinct (base, cand) name pairs plus the table that scores them."""
    table = {}
    for i in range(count):
        table[f"{prefix}-base-{i}"] = {0: base_score}
        table[f"{prefix}-cand-{i}"] = {0: cand_score}
    return table, [(f"{prefix}-base-{i}", f"{prefix}-cand-{i}") for i in range(count)]


# good: the oracle confirms the gain; flat: accepted, but no gain to confirm;
# bad: a regression the inner policy refuses before the verifier sees it.
VERIFIER = {"good-base": {0: 0.2}, "good-cand": {0: 0.9},
            "flat-base": {0: 0.5}, "flat-cand": {0: 0.5},
            "bad-base": {0: 0.9}, "bad-cand": {0: 0.2}}
ORACLE = {"good-base": {0: 0.2}, "good-cand": {0: 0.8},
          "flat-base": {0: 0.5}, "flat-cand": {0: 0.5},
          "bad-base": {0: 0.9}, "bad-cand": {0: 0.2}}


def _refuse_bad(ctx):
    return AcceptDecision(not ctx.artifact.name.startswith("bad"))


def test_a_thin_sample_defers_instead_of_demoting():
    """One or two audited rejections are "not yet", never a hard fail (#1035)."""
    for count in (1, 2):
        table, pairs = _pairs("thin", count, 0.2, 0.9)     # every candidate is good
        gate = _gate(table, table, REJECT)                  # ... and every one refused
        for base, cand in pairs:
            gate.accept(_ctx(base, cand))
        report = gate.admission_report()
        assert report.recommendation == "defer", report
        assert report.rejection_accuracy_upper is None or count < 3


def test_a_repeatedly_wrong_verifier_is_demoted_on_its_own_stratum():
    """Accepted commits the oracle denies are the verifier's false positives."""
    table, pairs = _pairs("fp", 5, 0.5, 1.2)      # the verifier "gains" 0.7 every time
    oracle, _ = _pairs("fp", 5, 0.5, 0.1)         # the oracle says -0.4 every time
    gate = _gate(table, oracle, ACCEPT)
    for base, cand in pairs:
        decision = gate.accept(_ctx(base, cand))
        assert not decision.accept                        # the audit still refuses
    report = gate.admission_report()
    assert (report.n_accepted, report.n_rejected) == (5, 0)   # its own decisions
    assert report.precision == 0.0                            # counted, not laundered
    assert report.recommendation == "reject"
    assert "oracle denies" in report.reason


def test_both_strata_and_the_bounds_that_admitted_them():
    table, pairs = _pairs("ok", 4, 0.2, 0.9)
    oracle, _ = _pairs("ok", 4, 0.2, 0.8)
    table.update(VERIFIER)
    oracle.update(ORACLE)
    gate = _gate(table, oracle, _refuse_bad)
    for base, cand in pairs:
        assert gate.accept(_ctx(base, cand)).accept
    gate.accept(_ctx("bad-base", "bad-cand"))                 # refused, and correct
    report = gate.admission_report()
    assert (report.n_accepted, report.n_rejected) == (4, 1)
    assert report.precision == 1.0
    assert report.precision_lower == 1.0 and report.precision_upper == 1.0
    assert report.recommendation == "defer"                   # one rejection is thin
    assert "insufficient evidence" in report.reason


def test_good_work_thrown_away_demotes_once_the_sample_is_thick_enough():
    table, pairs = _pairs("lost", 4, 0.2, 0.9)                 # every candidate is good
    gate = _gate(table, table, REJECT)                          # ... and every one refused
    for base, cand in pairs:
        gate.accept(_ctx(base, cand))
    report = gate.admission_report()
    assert report.precision is None                             # nothing was accepted
    assert report.rejection_accuracy_upper == 0.0
    assert report.recommendation == "reject"
    assert "rejects good work" in report.reason


def test_an_unmeasured_stratum_defers_and_never_reads_as_perfect():
    table, pairs = _pairs("only", 4, 0.2, 0.9)
    oracle, _ = _pairs("only", 4, 0.2, 0.8)
    gate = _gate(table, oracle, ACCEPT)
    for base, cand in pairs:
        assert gate.accept(_ctx(base, cand)).accept
    report = gate.admission_report()
    assert report.precision == 1.0 and report.rejection_accuracy_lower is None
    assert report.recommendation == "defer" and "rejection" in report.reason


def _verifier(**overrides):
    values = dict(votes=(), score=0.9, passed=True, confidence=1.0,
                  disagreement=0.0, cost=0.0, stopped_early=False)
    values.update(overrides)
    return EnsembleReport(**values)


def _promote(admission, require=True):
    return promote(
        PromotionRequest(artifact_id="skill-1",
                         verifier=_verifier(admission=admission)),
        PromotionRules(require_eval=False, require_contamination=False,
                       require_risk=False, require_canary=False,
                       require_verifier_admission=require))


_DEMOTE = AdmissionReport(
    n_accepted=4, n_rejected=4, precision=0.0, precision_lower=0.0,
    precision_upper=0.0, rejection_accuracy_lower=1.0, rejection_accuracy_upper=1.0,
    recommendation="reject", reason="precision 0.000 (at most 0.000): the oracle denies")


def test_promotion_defers_on_a_half_report_and_fails_closed_on_a_demote():
    for admission in (None,
                      replace(_DEMOTE, recommendation="defer",
                              reason="admission is incomplete: no rejection was audited")):
        decision = _promote(admission)
        assert decision.action == PromotionAction.DEFER
        assert "admission" in " ".join(decision.missing + decision.reasons)
    decision = _promote(_DEMOTE)
    assert decision.action == PromotionAction.REJECT   # a demote is not a deferral
    assert "oracle denies" in " ".join(decision.reasons)
    assert _promote(_DEMOTE, require=False).action == PromotionAction.PROMOTE


# --- cross-prompt error overlap (#940) -------------------------------------
# A prompt is one audit task. The same wrong answer accepted under several
# prompts is one systemic failure, not sampling noise, so the report carries
# the share of prompts on which each accepted error recurs.

TASKS = (0, 1, 2)


def _overlap_gate(err_prompts, *, tasks=TASKS, accepted=4, rejected=4):
    """A gate whose accepted commit ``i`` errs on exactly ``err_prompts[i]``."""
    verifier, oracle, pairs = {}, {}, []
    for i in range(accepted):
        base, cand = f"ok-base-{i}", f"ok-cand-{i}"
        pairs.append((base, cand))
        verifier[base] = {t: 0.1 for t in tasks}
        verifier[cand] = {t: 0.9 for t in tasks}          # claims a gain everywhere
        oracle[base] = {t: 0.1 for t in tasks}
        # The mean gain stays positive, so precision alone cannot see the error.
        oracle[cand] = {t: (-0.1 if t in err_prompts[i] else 1.0) for t in tasks}
    for i in range(rejected):
        base, cand = f"bad-base-{i}", f"bad-cand-{i}"
        pairs.append((base, cand))
        verifier[base] = oracle[base] = {t: 0.9 for t in tasks}
        verifier[cand] = oracle[cand] = {t: 0.2 for t in tasks}
    return _gate(verifier, oracle, _refuse_bad, tasks=tasks), pairs


def _admits(gate, pairs):
    for base, cand in pairs:
        gate.accept(_ctx(base, cand))
    return gate.admission_report()


def test_a_verifier_wrong_the_same_way_under_every_prompt_is_flagged():
    """Errors that recur across prompts block an admit the means would allow."""
    repeating, pairs = _overlap_gate([{0, 1}] * 4)
    report = _admits(repeating, pairs)
    assert report.precision == 1.0                       # the mean still looks right
    assert report.repeat_overlap == pytest.approx(2 / 3)
    assert report.high_universality is True
    assert report.recommendation == "defer"              # an admit on the means alone
    assert "same way" in report.reason and "0.667" in report.reason

    # Same evidence with the errors no longer shared: the means carry the gate.
    spread, spread_pairs = _overlap_gate([{0}, {1}, {2}, set()])
    spread_report = _admits(spread, spread_pairs)
    assert spread_report.repeat_overlap == pytest.approx(0.25)
    assert spread_report.high_universality is False
    assert spread_report.recommendation == "admit"

    # Offline and deterministic: the same draws produce the same report.
    assert asdict(report) == asdict(_admits(*_overlap_gate([{0, 1}] * 4)))


def test_one_prompt_cannot_overlap_with_itself():
    """A single probe task cannot show sharing: unknown, never 0.0."""
    gate, pairs = _overlap_gate([set()] * 4, tasks=(0,))
    report = _admits(gate, pairs)
    assert report.precision == 1.0
    assert report.repeat_overlap is None
    assert report.high_universality is False
    assert "overlap" not in report.reason
    assert report.recommendation == "admit"              # no evidence, so no bar


def test_a_thin_overlap_sample_is_not_evidence():
    """Two audited accepts are not a universality verdict (#940 bars)."""
    gate, pairs = _overlap_gate([{0, 1}] * 2, accepted=2)
    report = _admits(gate, pairs)
    assert report.repeat_overlap is None
    assert report.high_universality is False
    assert "overlap" not in report.reason
    assert "insufficient evidence" in report.reason
