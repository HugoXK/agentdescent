"""Co-evolving the verifier and the tasks it is judged on.

A verifier is a proxy. A curriculum that only samples tasks the verifier
already scores well measures the proxy against itself, so the two can agree
while both drift from the oracle (Goodhart). This module makes the curriculum
target the verifier's *disagreement* with oracle labels, and gives the verifier
a way to learn from those labels, so the task distribution and the proxy improve
against the same ground truth.

Two pieces, both independent of a model:

* :class:`VerifierCurriculum` -- probe a task pool with the verifier and the
  oracle, rank by the gap, and (optionally) feed the selected oracle labels back
  into the verifier via the caller's ``update`` callable.
* :class:`VerifierAgreement` -- an :class:`~agentdescent.policies.AcceptancePolicy`
  that audits a sample of commits against the oracle and refuses a
  verifier-only gain (the same failure the curriculum is looking for).

The verifier and oracle are ``(artifact, task) -> float`` callables, so this
works with the shipped verifier, a model judge, or a deterministic fixture.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .admission import AdmissionReport, admission_report
from .advantage import _ForwardsInstall
from .policies import AcceptDecision, MergeContext

__all__ = ["CoevolutionReport", "CoevolutionRound", "ProbeRow",
           "VerifierAgreement", "VerifierCurriculum"]

Scorer = Callable[[Any, Any], float]


def _mean_of(scores: Sequence[float]) -> float:
    return sum(scores) / len(scores) if scores else 0.0


def _overlap_share(base_v: Sequence[float], cand_v: Sequence[float],
                   base_o: Sequence[float], cand_o: Sequence[float]) -> float:
    """Share of prompts on which the verifier claims a gain the oracle denies."""
    wrong = sum(1 for bv, cv, bo, co in zip(base_v, cand_v, base_o, cand_o)
                if cv > bv and co <= bo)
    return wrong / len(base_v) if base_v else 0.0


@dataclass(frozen=True)
class ProbeRow:
    """One task's verifier and oracle scores, and how far apart they are."""

    task: Any
    verifier: float
    oracle: float

    @property
    def gap(self) -> float:
        return self.verifier - self.oracle

    @property
    def abs_gap(self) -> float:
        return abs(self.gap)


@dataclass(frozen=True)
class CoevolutionRound:
    """One curriculum step: the selected tasks, the bias before/after."""

    index: int
    tasks: Tuple[Any, ...]
    mean_gap: float
    abs_gap: float


@dataclass(frozen=True)
class CoevolutionReport:
    """The curriculum's effect on verifier/oracle agreement."""

    rounds: Tuple[CoevolutionRound, ...] = ()
    initial_abs_gap: float = 0.0
    final_abs_gap: float = 0.0
    improved: bool = False


class VerifierCurriculum:
    """Select the tasks where the verifier disagrees most with the oracle.

    ``probe`` scores every task with both callables. ``select`` takes the top
    ``n`` by absolute gap by default; ``mode='overestimate'`` targets the
    verifier being too generous and ``'underestimate'`` too harsh.
    ``coevolve`` repeats that selection and calls ``update(task, oracle_score)``
    for each selected task, so a caller can correct a contextual verifier. The
    ``update`` return value is ignored; the caller mutates its verifier.
    """

    def __init__(self, tasks: Sequence[Any], verifier: Scorer,
                 oracle: Scorer) -> None:
        self.tasks = tuple(tasks)
        self.verifier = verifier
        self.oracle = oracle

    def probe(self, artifact: Any) -> List[ProbeRow]:
        return [ProbeRow(task=task,
                         verifier=float(self.verifier(artifact, task)),
                         oracle=float(self.oracle(artifact, task)))
                for task in self.tasks]

    def _select_rows(self, rows: List[ProbeRow], n: int, *,
                     mode: str) -> List[ProbeRow]:
        if n <= 0 or not rows:
            return []
        if mode == "overestimate":
            rows.sort(key=lambda row: row.gap, reverse=True)
        elif mode == "underestimate":
            rows.sort(key=lambda row: row.gap)
        elif mode == "abs":
            rows.sort(key=lambda row: row.abs_gap, reverse=True)
        else:
            raise ValueError("mode must be 'abs', 'overestimate' or 'underestimate'")
        return rows[:n]

    def select(self, artifact: Any, n: int = 1, *,
               mode: str = "abs") -> List[Any]:
        return [row.task for row in self._select_rows(
            self.probe(artifact), n, mode=mode)]

    def coevolve(self, artifact: Any, *, rounds: int = 3, n: int = 4,
                 mode: str = "abs",
                 update: Optional[Callable[[Any, float], None]] = None,
                 ) -> CoevolutionReport:
        history: List[CoevolutionRound] = []
        initial = final = 0.0
        for index in range(max(0, rounds)):
            rows = self.probe(artifact)          # one oracle label per task this round
            if not rows:
                break
            if index == 0:
                initial = sum(row.abs_gap for row in rows) / len(rows)
            selected = self._select_rows(rows, n, mode=mode)
            selected_tasks = {id(row.task) for row in selected}
            if update is not None:
                for row in selected:
                    update(row.task, row.oracle)   # reuse the label already paid for
            # The verifier may have changed on the selected tasks; the oracle
            # labels are reused, so this costs verifier calls only.
            after = [ProbeRow(
                task=row.task,
                verifier=(float(self.verifier(artifact, row.task))
                          if id(row.task) in selected_tasks else row.verifier),
                oracle=row.oracle) for row in rows]
            mean_gap = sum(row.gap for row in after) / len(after)
            abs_gap = sum(row.abs_gap for row in after) / len(after)
            final = abs_gap
            history.append(CoevolutionRound(
                index=index, tasks=tuple(row.task for row in selected),
                mean_gap=mean_gap, abs_gap=abs_gap))
        return CoevolutionReport(
            rounds=tuple(history), initial_abs_gap=initial,
            final_abs_gap=final,
            improved=bool(history) and final < initial - 1e-12)


class VerifierAgreement(_ForwardsInstall):
    """Reject a commit whose gain the verifier claims and the oracle denies.

    ``audit_tasks`` is a fixed, held-out probe set (the same contract as an
    exam). A deterministic ``sample_rate`` fraction of commits is audited (the
    draw is seeded from the diff id, so it does not depend on merge order); the
    rest delegate straight to ``inner``. ``inner=None`` is the shipped
    ``DefaultAcceptance``, configured by the aggregator through the forwarded
    ``configure`` hook -- the wrapper can only make acceptance stricter. On an
    audit, an oracle regression is refused whatever the verifier says, and a
    verifier-only gain is refused with category ``oracle-disagrees``.

    ``rejected_sample_rate`` audits the rejected stratum by the same seeded
    rule (``:rejected`` suffix, off by default: it costs oracle calls).

    The report also carries the cross-prompt error overlap of the accepted
    stratum: the share of prompts on which the verifier claims a gain the oracle
    denies for the same commit. Errors that recur that way are one systemic
    failure, so they block an admit the mean gains would allow (#940).
    """

    def __init__(self, audit_tasks: Sequence[Any], verifier: Scorer, oracle: Scorer,
                 *, inner: Optional[Any] = None, sample_rate: float = 0.2,
                 rejected_sample_rate: float = 0.0, seed: int = 0) -> None:
        if not 0.0 <= sample_rate <= 1.0:
            raise ValueError("sample_rate must be in [0, 1]")
        if not 0.0 <= rejected_sample_rate <= 1.0:
            raise ValueError("rejected_sample_rate must be in [0, 1]")
        from .defaults import DefaultAcceptance

        self.audit_tasks = tuple(audit_tasks)
        self.verifier = verifier
        self.oracle = oracle
        self.inner = inner if inner is not None else DefaultAcceptance()
        self.sample_rate = float(sample_rate)
        self.rejected_sample_rate = float(rejected_sample_rate)
        self.seed = int(seed)
        self._n_accepted = 0
        self._n_rejected = 0
        self._accepted_confirmed: List[float] = []
        self._accepted_error_overlap: List[float] = []
        self._rejected_good: List[float] = []

    def _scores(self, scorer: Scorer, artifact: Any) -> Tuple[float, ...]:
        return tuple(float(scorer(artifact, task)) for task in self.audit_tasks)

    def _mean(self, scorer: Scorer, artifact: Any) -> float:
        return _mean_of(self._scores(scorer, artifact))

    def admission_report(self) -> AdmissionReport:
        """The audited decisions of both strata as one admission report."""
        return admission_report(
            n_accepted=self._n_accepted, n_rejected=self._n_rejected,
            rejected_sample_rate=self.rejected_sample_rate, seed=self.seed,
            accepted_confirmed=self._accepted_confirmed,
            rejected_good=self._rejected_good,
            accepted_error_overlap=self._accepted_error_overlap,
            prompts=len(self.audit_tasks))

    def accept(self, ctx: MergeContext) -> AcceptDecision:
        decision = (self.inner.accept(ctx) if hasattr(self.inner, "accept")
                    else self.inner(ctx))
        if not decision.accept:
            self._n_rejected += 1
            diff = getattr(ctx, "diff", None)  # same draw, other stratum
            key = f"{self.seed}:{getattr(diff, 'diff_id', '')}:rejected"
            if (self.audit_tasks
                    and random.Random(key).random() <= self.rejected_sample_rate):
                base_o = self._mean(self.oracle, ctx.artifact)
                cand_o = self._mean(self.oracle, ctx.candidate)
                self._rejected_good.append(1.0 if cand_o > base_o else 0.0)
            return decision
        # Counted before any audit override: the stratum is the verifier's own
        # decision, and a commit it accepted stays in the accepted stratum even
        # when the audit then refuses it -- otherwise the audit would launder the
        # verifier's false positives out of its own precision.
        self._n_accepted += 1
        diff = getattr(ctx, "diff", None)
        key = f"{self.seed}:{getattr(diff, 'diff_id', '')}"
        if random.Random(key).random() > self.sample_rate or not self.audit_tasks:
            return decision
        base_v = self._scores(self.verifier, ctx.artifact)
        cand_v = self._scores(self.verifier, ctx.candidate)
        base_o = self._scores(self.oracle, ctx.artifact)
        cand_o = self._scores(self.oracle, ctx.candidate)
        verifier_gain = _mean_of(cand_v) - _mean_of(base_v)
        oracle_gain = _mean_of(cand_o) - _mean_of(base_o)
        # Recorded before the audit's own override below: the stratum is the
        # verifier's decision, and one entry per audited accept keeps this share
        # aligned with ``_accepted_confirmed`` (#940).
        self._accepted_error_overlap.append(
            _overlap_share(base_v, cand_v, base_o, cand_o))
        if oracle_gain < 0.0:
            self._accepted_confirmed.append(0.0)   # accepted, the oracle denies
            return AcceptDecision(
                False, "oracle-regression",
                f"oracle {_mean_of(base_o):.3f} -> {_mean_of(cand_o):.3f} "
                f"on the audit set",
                observed_delta=0.0)
        if verifier_gain > 0.0 and oracle_gain <= 0.0:
            self._accepted_confirmed.append(0.0)
            return AcceptDecision(
                False, "oracle-disagrees",
                f"verifier {_mean_of(base_v):.3f} -> {_mean_of(cand_v):.3f} but oracle "
                f"{_mean_of(base_o):.3f} -> {_mean_of(cand_o):.3f}",
                observed_delta=0.0)
        self._accepted_confirmed.append(1.0 if oracle_gain > 0.0 else 0.0)
        return decision
