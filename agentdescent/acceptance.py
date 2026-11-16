"""Falsification-gated lesson admission (#938).

The shipped gate decides a commit from the held-out **counts** alone
(:class:`~agentdescent.defaults.DefaultAcceptance`). Those counts answer "is the
candidate better on the set we also selected on?" and nothing else. A lesson can
lift that number and still be wrong in the two ways that matter at review time:

* it did not transfer -- it only helps the task it was proposed on;
* it is over-broad -- it changes verdicts on tasks it was never meant to touch,
  or breaks one that used to work.

:class:`FalsificationAcceptance` puts three partitions in front of the commit:

``target``
    The tasks the lesson is supposed to transfer to. Requires a measured gain.
``archived``
    Tasks that used to pass. Any per-task regression refuses the commit.
``falsification``
    Tasks the lesson must not apply to. Any verdict change there refuses the
    commit: a rule that moves them is over-broad, and the reject reason names
    the ids so the evidence is the failing task, not an opinion.

Probes are caller-supplied in v1: the partitions come from the caller
(``FalsificationAcceptance(target=…, falsification=…, archived=…)``) and the
**evaluator** is supplied by the aggregator through
:attr:`~agentdescent.policies.MergeContext.probes`, so the policy cannot score
its own candidate. When the aggregator cannot supply probes the policy **defers**
(``AcceptDecision(defer=True)``): it never falls back to the count-only gate, and
it never reports a missing measurement as a rejection.

Reject detail carries the failing task ids:

``no-target-transfer``
    ids the candidate failed to move / moved backwards;
``archived-regression``
    ids whose reward dropped;
``falsification-moved``
    ids whose pass/fail verdict changed.

A committed lesson carries its review evidence on the decision
(:attr:`~agentdescent.policies.AcceptDecision.provenance`) instead of writing it
here: the aggregator stores it, after ``Ledger.commit`` returned, through
:func:`agentdescent.falsification.append_provenance`, which keeps records under
``<ledger>/.git/provenance/`` -- outside the work tree -- so the evidence can
never enter an artifact commit (#966) and a write can never bypass the CAS that
decided the commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .evolvable import stable_hash
from .policies import AcceptDecision, MergeContext

__all__ = [
    "FalsificationAcceptance",
    "ProbeContext",
    "ProbePartitions",
]


@dataclass(frozen=True)
class ProbePartitions:
    """The three task partitions a falsification gate measures on."""

    target: Sequence[Any]
    falsification: Sequence[Any]
    archived: Sequence[Any]


@dataclass(frozen=True)
class ProbeContext:
    """What the aggregator hands the gate: partitions **and** the evaluator.

    ``evaluate(artifact, tasks) -> {task_id: reward}`` is per-task on purpose:
    an aggregate float cannot name the task that regressed, and the reject
    reason has to name it.
    """

    target: Tuple[Any, ...]
    falsification: Tuple[Any, ...]
    archived: Tuple[Any, ...]
    evaluate: Callable[[Any, Sequence[Any]], Mapping[str, float]]


def _rate(scores: Mapping[str, float]) -> float:
    if not scores:
        return 0.0
    return sum(scores.values()) / len(scores)


def _verdict(reward: float, threshold: float) -> bool:
    return float(reward) >= threshold


def _ids(values: Iterable[str], limit: int = 8) -> str:
    names = sorted(values)
    shown = ", ".join(names[:limit])
    if len(names) > limit:
        shown += f", … ({len(names) - limit} more)"
    return shown


class FalsificationAcceptance:
    """Admit a lesson only when it transfers and stays narrowly scoped (#938).

    Fills the existing ``Policies(acceptance=...)`` slot. ``DefaultAcceptance``
    is untouched: this rule *replaces* the count-only gate for callers that opt
    in, and the aggregator only builds probes for a policy that declares
    ``needs_probes``.

    All three partitions are required and non-empty: the aggregator builds a
    probe context only when each has a task, so an empty one would leave every
    candidate deferred and nothing ever committed or rejected (#938).
    """

    #: The aggregator reads this to decide whether to build a
    #: :class:`ProbeContext` at all. A policy without it never pays for probes.
    needs_probes = True

    def __init__(self, *, target: Sequence[Any], falsification: Sequence[Any],
                 archived: Sequence[Any], verdict_threshold: float = 0.5,
                 min_gain: float = 0.0) -> None:
        if not target:
            raise ValueError("FalsificationAcceptance needs a non-empty target "
                             "partition: a gate with nothing to transfer to "
                             "cannot tell a lesson from a coincidence")
        if not archived:
            raise ValueError("FalsificationAcceptance needs a non-empty archived "
                             "partition: it is the regression guard")
        if not falsification:
            # Not a style rule: the aggregator builds probes only when all three
            # partitions are non-empty, so an empty one makes every candidate
            # defer (#938). A gate that admits nothing, silently, is worse than
            # a spec that refuses to start.
            raise ValueError("FalsificationAcceptance needs a non-empty "
                             "falsification partition: an empty one is never "
                             "measured, so every candidate would defer instead "
                             "of being committed or rejected")
        if not 0.0 <= min_gain < 1.0:
            raise ValueError(f"min_gain must be in [0, 1), got {min_gain}")
        self.target = tuple(target)
        self.falsification = tuple(falsification)
        self.archived = tuple(archived)
        self.verdict_threshold = float(verdict_threshold)
        self.min_gain = float(min_gain)

    # -- what the aggregator needs to know --------------------------------
    def probe_partitions(self) -> ProbePartitions:
        return ProbePartitions(target=self.target,
                               falsification=self.falsification,
                               archived=self.archived)

    # -- the gate ---------------------------------------------------------
    def accept(self, ctx: MergeContext) -> AcceptDecision:
        probes = ctx.probes
        if probes is None:
            return AcceptDecision(
                False, "probes-unavailable",
                "the aggregator supplied no probe partitions/evaluator, so "
                "target-transfer, archived regression and falsification cannot "
                "be measured; deferring instead of falling back to the count-only "
                "gate",
                defer=True)
        try:
            base_target = dict(probes.evaluate(ctx.artifact, probes.target))
            cand_target = dict(probes.evaluate(ctx.candidate, probes.target))
            base_archived = dict(probes.evaluate(ctx.artifact, probes.archived))
            cand_archived = dict(probes.evaluate(ctx.candidate, probes.archived))
            base_falsification = dict(
                probes.evaluate(ctx.artifact, probes.falsification))
            cand_falsification = dict(
                probes.evaluate(ctx.candidate, probes.falsification))
        except Exception as error:  # noqa: BLE001 - a failed probe is not a verdict
            return AcceptDecision(
                False, "probes-unavailable",
                f"probe evaluation failed ({type(error).__name__}: {error}); "
                "deferring instead of guessing",
                defer=True)

        base_rate = _rate(base_target)
        cand_rate = _rate(cand_target)
        gain = cand_rate - base_rate

        if gain <= self.min_gain:
            moved = [tid for tid in base_target
                     if cand_target.get(tid, 0.0) == base_target.get(tid, 0.0)]
            lost = [tid for tid in base_target
                    if cand_target.get(tid, 0.0) < base_target.get(tid, 0.0)]
            return AcceptDecision(
                False, "no-target-transfer",
                f"target-transfer has no measured gain "
                f"({base_rate:.3f} -> {cand_rate:.3f}, min_gain={self.min_gain}); "
                f"unchanged ids: {_ids(moved)}"
                + (f"; regressed ids: {_ids(lost)}" if lost else ""),
                observed_delta=gain)

        regressed = [tid for tid in base_archived
                     if cand_archived.get(tid, 0.0) < base_archived.get(tid, 0.0)]
        if regressed:
            return AcceptDecision(
                False, "archived-regression",
                f"the candidate transfers ({base_rate:.3f} -> {cand_rate:.3f}) "
                f"but regresses archived task(s): {_ids(regressed)}",
                observed_delta=gain)

        moved = [tid for tid in base_falsification
                 if _verdict(cand_falsification.get(tid, 0.0), self.verdict_threshold)
                 != _verdict(base_falsification.get(tid, 0.0), self.verdict_threshold)]
        if moved:
            return AcceptDecision(
                False, "falsification-moved",
                f"the candidate transfers ({base_rate:.3f} -> {cand_rate:.3f}) "
                "but changes a verdict on the falsification partition, so it is "
                f"over-broad; failing ids: {_ids(moved)}",
                observed_delta=gain)

        return AcceptDecision(True, "committed", "", observed_delta=gain,
                              provenance=self._provenance(ctx, base_rate, cand_rate))

    # -- review evidence ---------------------------------------------------
    def _provenance(self, ctx: MergeContext, base_rate: float,
                    cand_rate: float) -> Dict[str, Any]:
        diff = ctx.diff
        cards = list(ctx.cards or ())
        trace_ids: List[str] = []
        for card in cards:
            trace_ids.extend(str(t) for t in getattr(card, "trace_ids", ()) or ())
        card_ids = sorted(str(getattr(getattr(c, "diff", None), "diff_id", ""))
                          for c in cards)
        rule_id = (getattr(diff, "diff_id", None)
                   or f"{getattr(ctx.candidate, 'id', 'artifact')}"
                      f"@v{getattr(ctx.candidate, 'version', 1)}")
        return {
            "rule_id": str(rule_id),
            "precondition": (f"base v{getattr(ctx.artifact, 'version', 1)}; "
                             f"{len(cards)} evidence card(s)"),
            "behavior_change": sorted(getattr(diff, "ops", {}) or {}),
            "expected_effect": {"base": round(base_rate, 6),
                                "candidate": round(cand_rate, 6)},
            "verifier": "falsification-probes:v1",
            "trace_ids": sorted(set(trace_ids)),
            "evidence_card_hash": f"{stable_hash(tuple(card_ids)) & 0xFFFFFFFF:08x}",
        }
