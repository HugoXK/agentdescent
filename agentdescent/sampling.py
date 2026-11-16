"""Which task should a worker roll out next? (design doc, section 5.2 -- L-task)

A rollout is the expensive unit of work: one LLM call, or a whole tool-using agent
trajectory that can run for minutes. Spending it on a task the agent *already*
solves teaches the system nothing -- there is no failure to learn from, so no diff
is proposed and the rollout is wasted.

The reference :class:`~agentdescent.scheduler.TaskScheduler` solves this for the
stage-orchestration runtime with UCB over task *clusters* plus a difficulty
filter. This module brings the same idea to the :func:`~agentdescent.evolution.evolve`
engine at *task* granularity, as a plug-in:

* :class:`RoundRobin` -- cycle through the shard (the default; fully deterministic).
* :class:`DifficultyWeighted` -- prefer tasks that carry a learning signal, i.e.
  whose pass rate sits away from the all-pass / all-fail extremes, with a UCB
  exploration bonus so rarely-tried tasks still get sampled.

Both satisfy the :class:`TaskSampler` protocol structurally, so you can pass your
own::

    evolve(tasks, reward, agent=agent, task_sampler=DifficultyWeighted())
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import defaultdict
from dataclasses import dataclass

from .evolvable import EvidenceCard
from .stats import difficulty_weight
from typing import (
    Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence,
    Tuple, runtime_checkable,
)


@runtime_checkable
class TaskSampler(Protocol):
    """Chooses the next task id for a worker, and learns from the outcome."""

    def pick(self, keys: Sequence[str], round_index: int) -> str:
        """Return one task id from ``keys`` (never mutate ``keys``)."""
        ...

    def record(self, task_id: str, score: float) -> None:
        """Report the reward a rollout of ``task_id`` achieved (0..1)."""
        ...


class RoundRobin:
    """Cycle through the shard in order -- the deterministic default.

    Reproducible and dependency-free, but it spends rollouts uniformly, including
    on tasks the agent already solves.
    """

    name = "round-robin"

    def pick(self, keys: Sequence[str], round_index: int) -> str:
        if not keys:
            raise ValueError("task_sampler.pick() got an empty key list")
        return keys[round_index % len(keys)]

    def record(self, task_id: str, score: float) -> None:  # nothing to learn
        return None


class DifficultyWeighted:
    """UCB over tasks, weighted by how much learning signal each one carries.

    The weight ``4*p*(1-p)`` (``p`` = observed pass rate) peaks at ``p = 0.5`` and
    vanishes at the extremes: a task that always passes -- or never passes no
    matter the artifact -- yields no usable gradient (the GRPO zero-advantage
    argument), so it is down-weighted in favour of tasks that sometimes fail.
    An untried task keeps the optimistic prior ``p = 0.5`` and a large UCB bonus,
    so exploration still happens.

    ``pass_threshold`` mirrors the engine: a rollout counts as a pass when its
    reward reaches it.

    ``c`` is the UCB exploration constant, and the default is deliberately much
    smaller than the textbook ``1.4``. Most of the exploration here comes from the
    **optimistic prior**: an untried task is assumed to sit at ``p = 0.5``, which
    is exactly where the signal weight is *maximal*, so it is already picked
    eagerly. A large ``c`` on top of that swamps the signal term (which is capped
    at 1.0) and the sampler never stops re-trying tasks it has already shown to be
    uninformative. Measured on a 40-task workload where only 6 tasks carry signal
    (share of rollouts that landed on an informative task, higher is better)::

        c            1.4     0.7     0.4     0.2     0.1     round-robin
        clean       15.5%   19.3%   21.0%   23.4%   27.4%      14.5%
        15% noise      --      --   11.5%   16.3%   18.1%       7.3%

    ``0.2`` is the default: ~1.6-2.2x better than round-robin in both regimes
    while keeping twice the exploration of the empirical optimum, which matters on
    workloads whose reward is noisier than the ones measured here. Lower it to
    focus harder, raise it to explore more.
    """

    name = "difficulty-weighted"

    def __init__(self, c: float = 0.2, pass_threshold: Optional[float] = None,
                 prior: float = 0.5) -> None:
        self.c = c
        # Defaults to the engine's own SOLVED rather than repeating the
        # literal: the docstring says this 'mirrors the engine', which is
        # exactly the coupling a shared constant should carry.
        from .evolution import SOLVED
        self.pass_threshold = SOLVED if pass_threshold is None else pass_threshold
        self.prior = prior
        # task_id -> (passes, trials); untried tasks fall back to the prior.
        self._stats: Dict[str, Tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))
        self._t = 0
        self._lock = threading.Lock()      # worker threads share one sampler

    def _pass_rate(self, task_id: str) -> float:
        passes, trials = self._stats[task_id]
        if trials <= 0:
            return self.prior
        return passes / trials

    @staticmethod
    def _signal(pass_rate: float) -> float:
        """Learning signal: peaks at pass_rate 0.5, ~0 when always/never solved.

        Shared with :class:`~agentdescent.scheduler.TaskScheduler`, which applies
        the same weight one granularity up (clusters rather than tasks)."""
        return difficulty_weight(pass_rate, floor=1e-3)

    def pick(self, keys: Sequence[str], round_index: int) -> str:
        if not keys:
            raise ValueError("task_sampler.pick() got an empty key list")
        with self._lock:
            self._t += 1
            total = float(self._t)
            best, best_score = keys[0], float("-inf")
            for k in keys:
                _, trials = self._stats[k]
                value = self._signal(self._pass_rate(k))
                # UCB: unexplored tasks (trials == 0) win outright.
                bonus = (self.c * math.sqrt(math.log(total + 1.0) / trials)
                         if trials > 0 else float("inf"))
                score = value + bonus
                if score > best_score:
                    best, best_score = k, score
            return best

    def record(self, task_id: str, score: float) -> None:
        with self._lock:
            passes, trials = self._stats[task_id]
            self._stats[task_id] = (passes + (1.0 if score >= self.pass_threshold else 0.0),
                                    trials + 1.0)

    def stats(self) -> Dict[str, Tuple[float, float]]:
        """Copy of the per-task (passes, trials) counters -- for inspection/tests."""
        with self._lock:
            return dict(self._stats)


class ReplaySampler:
    """A :class:`TaskSampler` that also learns from discarded evidence.

    The engine's aggregator settles the diff it discards -- stale, oversized, or
    lost to a CAS race -- into a bounded pool (``aggregator.settle``). Nobody reads
    it back. This sampler subscribes to that pool and up-weights tasks whose recent
    proposals were thrown away, on the argument that the waste is a signal *of its
    own*: a task that always passes and a task whose proposals keep going stale are
    both "not producing accepted diffs", but the first should be down-weighted
    (nothing to learn) and the second should be up-weighted (the parallel scheduler
    keeps out-competing it, not because it is easy).

    The base score is :class:`DifficultyWeighted`'s -- the pass-rate signal plus a
    UCB exploration bonus. The replay bonus is additive and saturating: a task with
    ``capped_at`` recent settled cards gets the full ``temperature``, so a task
    cannot dominate the score by being out-competed many times.

    ``temperature=0`` (the default) reproduces the base sampler exactly; without a
    wired aggregator the counts never increase, so the bonus stays zero. Wire one:

    .. code-block:: python

        sampler = ReplaySampler(temperature=0.3)
        evolve(tasks, reward, agent=agent, task_sampler=sampler,
               ...)  # the engine calls aggregator.set_settled_consumer(sampler.settle)
    """

    name = "replay"

    def __init__(self, temperature: float = 0.0, capped_at: int = 10) -> None:
        self._base = DifficultyWeighted()
        self.temperature = temperature
        self.capped_at = capped_at
        #: task_id -> number of settled evidence cards the pool handed to this
        #: sampler, counted since construction.
        self._settled_count: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        #: Picks made, and picks where the replay bonus changed the winner --
        #: the observable that tells a run the mechanism fired at all.
        self.picks = 0
        self.replay_affected = 0

    def settle(self, card: EvidenceCard) -> None:
        """Consume one settled evidence card (called by the aggregator's pool).

        ``trajectory_refs`` carries the task objects the diff was rolled out
        against; a card may name several, and every one of them was implicated in
        the discard.
        """
        for ref in card.trajectory_refs:
            task_id = getattr(ref, "id", None)
            if task_id is None:
                continue
            with self._lock:
                self._settled_count[task_id] = self._settled_count[task_id] + 1

    def pick(self, keys: Sequence[str], round_index: int) -> str:
        if not keys:
            raise ValueError("task_sampler.pick() got an empty key list")
        with self._lock:
            self._base._t += 1
            total = float(self._base._t)

            def score_of(k: str, with_replay: bool) -> float:
                passes, trials = self._base._stats[k]
                signal = self._base._signal(
                    passes / trials if trials else self._base.prior)
                bonus = (self._base.c * math.sqrt(
                    math.log(total + 1.0) / trials) if trials > 0 else float("inf"))
                out = signal + bonus
                if with_replay:
                    out += self.temperature * min(
                        self.capped_at, self._settled_count.get(k, 0))
                return out

            base_winner = max(keys, key=lambda k: score_of(k, with_replay=False))
            winner = max(keys, key=lambda k: score_of(k, with_replay=True))
            # replay changed the outcome when the winner differs from the base winner
            if self.temperature > 0 and self._settled_count.get(winner, 0) > 0 \
                    and winner != base_winner:
                self.replay_affected += 1
            self.picks += 1
            return winner

    def record(self, task_id: str, score: float) -> None:
        self._base.record(task_id, score)

    def stats(self) -> Dict[str, Tuple[float, float]]:
        """Copy of the base sampler's per-task (passes, trials) counters."""
        return self._base.stats()

    def settled_counts(self) -> Dict[str, int]:
        """Copy of the per-task settled-card counts -- for inspection/tests."""
        with self._lock:
            return dict(self._settled_count)


_SPLITS = ("search", "select", "final")


@dataclass(frozen=True)
class TaskSplit:
    """The three disjoint task sets a stratified sampler works from.

    ``search`` is what the proposer is allowed to see; ``select`` is the hidden
    validation set a candidate is compared against; ``final`` is the held-out set
    a promotion is measured on. The sampler assigns each task to exactly one of
    them, so overlap is empty by construction. :meth:`overlap` still computes it
    explicitly: a leaked task must be visible in a report, not assumed absent.
    """

    search: Tuple[str, ...] = ()
    select: Tuple[str, ...] = ()
    final: Tuple[str, ...] = ()

    def overlap(self) -> Dict[str, Tuple[str, ...]]:
        """Task id -> the split names it appears in, only for leaked ids."""
        where: Dict[str, set] = defaultdict(set)  # type: ignore[type-arg]
        for name, ids in zip(_SPLITS, (self.search, self.select, self.final)):
            for task_id in ids:
                where[task_id].add(name)
        return {task_id: tuple(sorted(names))
                for task_id, names in sorted(where.items())
                if len(names) > 1}

    def is_disjoint(self) -> bool:
        return not self.overlap()

    def all_ids(self) -> Tuple[str, ...]:
        return self.search + self.select + self.final


@dataclass(frozen=True)
class StratumCoverage:
    """How one failure stratum is split and how much of it was sampled."""

    stratum: str
    total: int
    search: int
    select: int
    final: int
    picks: int
    share: float
    pick_share: float
    starved: bool


@dataclass(frozen=True)
class TransferStatus:
    """Whether gains measured on ``select`` survive on ``final``.

    The sampler only picks ``search`` tasks, so this stays ``no_data`` until the
    caller reports scores for tasks it assigned to the two hidden sets with
    :meth:`FailureStratifiedSampler.record`.
    """

    select_n: int
    final_n: int
    select_mean: Optional[float]
    final_mean: Optional[float]
    gap: Optional[float]
    status: str


@dataclass(frozen=True)
class SamplingReport:
    """Stratum coverage, split overlap and transfer status for one sampler."""

    split: TaskSplit
    coverage: Mapping[str, StratumCoverage]
    overlap: Mapping[str, Tuple[str, ...]]
    starved: Tuple[str, ...]
    ignored: Tuple[str, ...]
    dominant: Tuple[str, ...]
    warnings: Tuple[str, ...]
    transfer: TransferStatus
    picks: int


_FLOAT_EPS = 1e-12
# Two means of identical scores differ by ~1e-16 depending on the summation
# order, so a tolerance of 0.0 must still read "holds" instead of flipping the
# status on that noise.


class FailureStratifiedSampler:
    """Sample across base-failure strata, not from whichever mode is largest.

    A search set dominated by one failure mode teaches the proposer that mode and
    the gain disappears on held-out tasks (the HDA finding; StarHarness builds
    its pool the same way). This sampler fixes the pool before the run: tasks are
    grouped by a base failure signature -- a task family, an error type, or any
    user-supplied label -- and each stratum is split across three disjoint sets::

        search  the only set pick() will ever return; visible to the proposer
        select  hidden validation tasks used to choose between candidates
        final   hidden held-out tasks used to judge whether the gain transfers

    Every task in the universe goes to exactly one set, so the intersection is
    empty by construction. :meth:`report` recomputes it anyway and warns about a
    leaked task, a dominant stratum, a stratum the run never sampled, and a
    selection gain that does not hold on the final set.

    ``signature`` is a mapping from task id to label, or a callable that receives
    a task id and returns one. Without it every task shares the ``"all"`` stratum
    and only the disjoint split remains useful. Pass ``tasks`` when the signature
    is callable so the full universe is split up front; otherwise new ids are
    assigned deterministically the first time ``pick`` or ``record`` sees them.

    ``min_per_stratum`` is the number of picks each populated stratum gets before
    the sampler spends a second pick on any of them. ``search_frac``,
    ``select_frac`` and ``final_frac`` are relative weights, not required to sum
    to one, but ``search_frac`` must be positive. A stratum with at least as many
    tasks as nonzero weights receives at least one task in every such split.

    ``dominant_share`` is the warning threshold: a stratum holding at least this
    share of the tasks or of the picks is reported as dominant. ``seed`` makes
    the within-stratum assignment reproducible.

    The engine shares one sampler across worker threads, so every method locks.
    """

    name = "failure-stratified"

    def __init__(self, signature: Optional[Any] = None, *,
                 tasks: Optional[Sequence[str]] = None,
                 min_per_stratum: int = 1,
                 search_frac: float = 0.5,
                 select_frac: float = 0.25,
                 final_frac: float = 0.25,
                 dominant_share: float = 0.6,
                 transfer_tolerance: float = 0.0,
                 seed: int = 0) -> None:
        if isinstance(min_per_stratum, bool) or not isinstance(min_per_stratum, int) \
                or min_per_stratum < 1:
            raise ValueError("min_per_stratum must be an int of at least 1")
        weights = (search_frac, select_frac, final_frac)
        for name, value in zip(_SPLITS, weights):
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name}_frac must be a finite number >= 0")
        if float(search_frac) <= 0.0:
            raise ValueError("search_frac must be positive: the proposer needs tasks")
        if isinstance(dominant_share, bool) \
                or not isinstance(dominant_share, (int, float)) \
                or not 0.0 < float(dominant_share) <= 1.0:
            raise ValueError("dominant_share must be in (0, 1]")
        if isinstance(transfer_tolerance, bool) \
                or not isinstance(transfer_tolerance, (int, float)) \
                or not math.isfinite(float(transfer_tolerance)) \
                or float(transfer_tolerance) < 0.0:
            raise ValueError("transfer_tolerance must be a finite number >= 0")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an int")
        if signature is not None and not callable(signature) \
                and not isinstance(signature, Mapping):
            raise TypeError("signature must be a mapping or a callable")
        self.min_per_stratum = min_per_stratum
        self.search_frac = float(search_frac)
        self.select_frac = float(select_frac)
        self.final_frac = float(final_frac)
        self._weights = (self.search_frac, self.select_frac, self.final_frac)
        self.dominant_share = float(dominant_share)
        self.transfer_tolerance = float(transfer_tolerance)
        self.seed = seed
        # Copy a mapping so a caller mutating its dict cannot move a task to a
        # different stratum after the split was fixed.
        self._labels: Optional[Dict[str, str]] = (
            {str(k): str(v) for k, v in signature.items()}
            if isinstance(signature, Mapping) else None)
        self._signature: Optional[Callable[[str], str]] = (
            signature if callable(signature) else None)
        self._lock = threading.Lock()
        self._assignment: Dict[str, str] = {}
        self._stratum_picks: Dict[str, int] = defaultdict(int)
        self._task_picks: Dict[str, int] = defaultdict(int)
        self._split_scores: Dict[str, List[float]] = {
            name: [] for name in _SPLITS}
        universe: List[str] = []
        if tasks is not None:
            universe.extend(str(task) for task in tasks)
        if self._labels is not None:
            universe.extend(self._labels)
        if universe:
            with self._lock:
                self._assign_locked(universe)

    # -- stratification and the disjoint split --------------------------------

    def _stratum(self, task_id: str) -> str:
        if self._labels is not None:
            return self._labels.get(task_id, "unlabelled")
        if self._signature is not None:
            return str(self._signature(task_id))
        return "all"

    def _order_key(self, stratum: str, task_id: str) -> bytes:
        raw = f"{self.seed}:{stratum}:{task_id}".encode("utf-8")
        return hashlib.sha256(raw).digest()

    def _allocate(self, n: int) -> List[int]:
        """Counts per split for ``n`` tasks of one stratum."""
        counts = [0, 0, 0]
        if n <= 0:
            return counts
        active = [i for i, w in enumerate(self._weights) if w > 0.0]
        if n < len(active):
            # Too few tasks to cover every requested split: spend them on the
            # heaviest splits first. Search is always first because its weight
            # must be positive, so a stratum is never invisible to the proposer.
            for i in sorted(active, key=lambda j: (-self._weights[j], j))[:n]:
                counts[i] = 1
            return counts
        total = sum(self._weights)
        raw = [n * w / total for w in self._weights]
        counts = [int(math.floor(value)) for value in raw]
        remaining = n - sum(counts)
        order = sorted(active, key=lambda i: (-(raw[i] - counts[i]), i))
        for i in order[:remaining]:
            counts[i] += 1
        # Give every active split one task, taking it from the largest split.
        # Without this a small stratum (three tasks, weights 0.5/0.25/0.25)
        # can hand all three tasks to search and leave the hidden sets empty.
        for i in active:
            if counts[i] > 0:
                continue
            donor = max(active, key=lambda j: (counts[j], -j))
            if counts[donor] > 1:
                counts[donor] -= 1
                counts[i] += 1
        return counts

    def _assign_locked(self, ids: Iterable[str]) -> None:
        grouped: Dict[str, List[str]] = defaultdict(list)
        for raw in ids:
            task_id = str(raw)
            if task_id not in self._assignment:
                grouped[self._stratum(task_id)].append(task_id)
        for stratum in sorted(grouped):
            ordered = sorted(set(grouped[stratum]),
                             key=lambda task_id: self._order_key(stratum, task_id))
            counts = self._allocate(len(ordered))
            cursor = 0
            for name, count in zip(_SPLITS, counts):
                for task_id in ordered[cursor:cursor + count]:
                    self._assignment[task_id] = name
                cursor += count

    def _split_locked(self, ids: Iterable[str]) -> TaskSplit:
        grouped: Dict[str, List[str]] = {name: [] for name in _SPLITS}
        for task_id in ids:
            split_name = self._assignment.get(str(task_id))
            if split_name is not None:
                grouped[split_name].append(str(task_id))
        return TaskSplit(
            search=tuple(sorted(grouped["search"])),
            select=tuple(sorted(grouped["select"])),
            final=tuple(sorted(grouped["final"])))

    def split(self, keys: Optional[Sequence[str]] = None) -> TaskSplit:
        """The fixed split, assigning ``keys`` first when given.

        Call this once with the whole task universe before the run. Later calls
        with new ids only assign the new ids; an id already in the split never
        moves, so a task cannot silently cross from ``final`` to ``search``.
        """
        with self._lock:
            if keys is None:
                universe = sorted(self._assignment)
            else:
                self._assign_locked(keys)
                universe = list(dict.fromkeys(str(k) for k in keys))
            return self._split_locked(universe)

    def stratum_of(self, task_id: str) -> str:
        """The base failure signature this task belongs to."""
        return self._stratum(str(task_id))

    # -- the TaskSampler protocol ---------------------------------------------

    def pick(self, keys: Sequence[str], round_index: int) -> str:
        """Return a ``search`` task from ``keys``, rotating across strata.

        The least-sampled stratum goes first, so every populated stratum reaches
        ``min_per_stratum`` picks before any stratum gets another. Hidden
        ``select`` / ``final`` ids are never returned: if ``keys`` contains only
        those, the pick is refused rather than leaking a held-out task.
        """
        if not keys:
            raise ValueError("task_sampler.pick() got an empty key list")
        with self._lock:
            self._assign_locked(keys)
            candidates = [str(k) for k in keys
                          if self._assignment.get(str(k)) == "search"]
            if not candidates:
                raise ValueError(
                    "FailureStratifiedSampler.pick() got no search task in this "
                    "key list; select/final tasks are hidden from the proposer. "
                    "Pass sampler.split()['search'] (not the whole task list) as "
                    "tasks to evolve(), so every worker shard holds search ids")
            by_stratum: Dict[str, List[str]] = defaultdict(list)
            for task_id in candidates:
                by_stratum[self._stratum(task_id)].append(task_id)
            fewest = min(self._stratum_picks[stratum]
                         for stratum in by_stratum)
            eligible = sorted(stratum for stratum in by_stratum
                              if self._stratum_picks[stratum] == fewest)
            stratum = eligible[round_index % len(eligible)]
            ids = sorted(by_stratum[stratum])
            fewest_task = min(self._task_picks[task_id] for task_id in ids)
            tied = [task_id for task_id in ids
                    if self._task_picks[task_id] == fewest_task]
            chosen = tied[round_index % len(tied)]
            self._stratum_picks[stratum] += 1
            self._task_picks[chosen] += 1
            return chosen

    def record(self, task_id: str, score: float) -> None:
        """Report a rollout score; select/final scores feed the transfer report."""
        task_id = str(task_id)
        with self._lock:
            if task_id not in self._assignment:
                self._assign_locked([task_id])
            split_name = self._assignment.get(task_id)
            if split_name is not None:
                self._split_scores[split_name].append(float(score))

    def _transfer_locked(self) -> TransferStatus:
        select = self._split_scores["select"]
        final = self._split_scores["final"]
        select_mean = sum(select) / len(select) if select else None
        final_mean = sum(final) / len(final) if final else None
        if select_mean is None or final_mean is None:
            return TransferStatus(
                select_n=len(select), final_n=len(final),
                select_mean=select_mean, final_mean=final_mean,
                gap=None, status="no_data")
        gap = select_mean - final_mean
        # A final mean at least as high as select (within tolerance) means the
        # selection gain survived the hidden set. Anything below is the HDA
        # failure this sampler exists to make visible. The comparison keeps a
        # float floor: equal means must report "holds" even at tolerance 0.0,
        # otherwise the last bits of the summation decide the status.
        tolerance = max(self.transfer_tolerance, _FLOAT_EPS)
        if math.isclose(gap, 0.0, abs_tol=tolerance):
            status = "holds"
        elif gap > 0.0:
            status = "degrades"
        else:
            status = "improves"
        return TransferStatus(
            select_n=len(select), final_n=len(final),
            select_mean=select_mean, final_mean=final_mean,
            gap=gap, status=status)

    # -- reporting ------------------------------------------------------------

    def report(self) -> SamplingReport:
        """Coverage, overlap, warnings and transfer status at this point."""
        with self._lock:
            universe = sorted(self._assignment)
            split = self._split_locked(universe)
            total = len(universe)
            total_picks = sum(self._stratum_picks.values())
            strata = sorted({self._stratum(task_id) for task_id in universe})
            coverage: Dict[str, StratumCoverage] = {}
            starved: List[str] = []
            ignored: List[str] = []
            dominant: List[str] = []
            warnings: List[str] = []
            overlap = split.overlap()
            if overlap:
                warnings.append(
                    "task(s) leaked across splits: "
                    + ", ".join(sorted(overlap)))
            for stratum in strata:
                ids = [task_id for task_id in universe
                       if self._stratum(task_id) == stratum]
                counts = {name: 0 for name in _SPLITS}
                for task_id in ids:
                    counts[self._assignment[task_id]] += 1
                picks = self._stratum_picks[stratum]
                share = len(ids) / total if total else 0.0
                pick_share = picks / total_picks if total_picks else 0.0
                is_starved = (counts["search"] == 0
                              or (total_picks > 0
                                  and picks < self.min_per_stratum))
                if is_starved:
                    starved.append(stratum)
                if total_picks > 0 and picks == 0:
                    ignored.append(stratum)
                # One stratum is 100% of the tasks by construction; calling
                # that "dominant" is noise, not a finding.
                if len(strata) > 1 \
                        and max(share, pick_share) >= self.dominant_share:
                    dominant.append(stratum)
                coverage[stratum] = StratumCoverage(
                    stratum=stratum, total=len(ids),
                    search=counts["search"], select=counts["select"],
                    final=counts["final"], picks=picks, share=share,
                    pick_share=pick_share, starved=is_starved)
                if counts["search"] == 0:
                    warnings.append(
                        f"stratum '{stratum}' has no search task; the proposer "
                        "cannot learn from it")
                elif total_picks > 0 and picks < self.min_per_stratum:
                    warnings.append(
                        f"stratum '{stratum}' is starved: {picks} pick(s), "
                        f"minimum is {self.min_per_stratum}")
                if total_picks > 0 and picks == 0:
                    warnings.append(
                        f"stratum '{stratum}' was ignored: 0 of "
                        f"{total_picks} picks")
                if len(strata) > 1 \
                        and max(share, pick_share) >= self.dominant_share:
                    warnings.append(
                        f"stratum '{stratum}' is dominant: {share:.0%} of tasks, "
                        f"{pick_share:.0%} of picks; coverage is unbalanced")
            transfer = self._transfer_locked()
            if transfer.status == "degrades":
                warnings.append(
                    "selection gain does not transfer: select mean "
                    f"{transfer.select_mean:.3f} vs final mean "
                    f"{transfer.final_mean:.3f}")
            return SamplingReport(
                split=split, coverage=coverage, overlap=overlap,
                starved=tuple(starved), ignored=tuple(ignored),
                dominant=tuple(dominant), warnings=tuple(warnings),
                transfer=transfer, picks=total_picks)
