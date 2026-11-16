"""Cost per accepted diff, and the quality-per-cost acceptance gate (#945).

The shipped gate answers "is the candidate better on held-out?". It never
answers "was that improvement worth what it cost", so a candidate that adds
+0.10 for five times the tokens can win against one that adds +0.09 for 1.1x.
This module is the second ledger, at transaction grain:

``Cost``
    One diff's price: calls, prompt/completion tokens, wall seconds and an
    optional USD estimate. Every field is ``Optional`` on purpose -- a number we
    did not measure is ``None``, never ``0``, because zero is a real measurement
    ("this diff was free") and a missing one is not.

``cost_efficiency``
    The derived ``quality_per_cost`` the issue names: delta per 1k tokens or per
    USD. ``None`` when there is no positive gain or no unit to divide by -- a
    quality *loss* is not a cost-efficiency number.

``cost_status``
    ``improved | neutral | regressed | unknown`` against a caller-supplied
    reference. Unknown is the honest answer to "no reference" and "no
    measurement"; it is not rounded into neutral.

``CostPolicy``
    An acceptance wrapper: the inner gate decides quality first (a cost win
    never rescues a rejected candidate), then the wrapper refuses a quality gain
    whose efficiency regressed against a reference or fell below a floor.
    ``require_cost=True`` defers instead of treating an unpriced diff as free.

``cost_report`` / ``CostReport``
    What the issue asks a report to show: calls/tokens/USD per accepted diff and
    per point of gain, with ``missing_cost`` counted rather than zeroed.

Placement of the price is caller-supplied by design.
:class:`~agentdescent.policies.MergeContext` carries ``diff_cost`` when a
caller supplies one, and a caller that wants the gate to price a diff passes
``Cost.from_usage(usage)`` there. The policy otherwise falls back to the cost
the contributing
:class:`~agentdescent.evolvable.EvidenceCard`\\ s recorded -- and in-tree no
producer writes ``cost_tokens``/``cost_wallclock`` onto a card, so that
fallback is unknown, never a free diff. ``aggregator._decide`` does not fill
``diff_cost`` yet, so the card fallback is what every in-tree caller takes
today.
``agentdescent.promotion.PromotionRules.require_cost``
is the matching fail-closed bar on the promotion side.

Not here: provider billing, a price table, or a claim that tokens are the only
cost axis. ``Cost.usd`` is whatever the caller measured; this module never
invents a price (issue #945 non-goals).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional

from .policies import AcceptDecision, MergeContext

__all__ = [
    "Cost",
    "CostPolicy",
    "CostReport",
    "cost_efficiency",
    "cost_report",
    "cost_status",
]

UNKNOWN = "unknown"
IMPROVED = "improved"
NEUTRAL = "neutral"
REGRESSED = "regressed"

_UNITS = ("1k_tokens", "usd")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not bool")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite and non-negative")
    if number < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a non-negative int")
    if value < 0:
        raise ValueError(f"{name} must be a non-negative int")
    return value


@dataclass(frozen=True)
class Cost:
    """What one diff cost, with ``None`` for every number not measured.

    ``tokens`` is the total when the prompt/completion split is unknown (a card
    records one total), and is filled from the split when both halves are known.
    Supplying both a split and a conflicting total is refused: two numbers for
    one quantity is how a report starts disagreeing with itself.
    """

    calls: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    tokens: Optional[int] = None
    wallclock: Optional[float] = None
    usd: Optional[float] = None

    def __post_init__(self) -> None:
        for name in ("calls", "prompt_tokens", "completion_tokens", "tokens"):
            value = getattr(self, name)
            if value is not None:
                _count(value, name)
        for name in ("wallclock", "usd"):
            value = getattr(self, name)
            if value is not None:
                _finite(value, name)
        if self.prompt_tokens is not None and self.completion_tokens is not None:
            split = self.prompt_tokens + self.completion_tokens
            if self.tokens is None:
                object.__setattr__(self, "tokens", split)
            elif self.tokens != split:
                raise ValueError(
                    f"tokens is inconsistent with prompt_tokens + "
                    f"completion_tokens ({self.tokens} != {split})")

    @property
    def known(self) -> bool:
        """Did anyone measure anything about this diff's cost?"""
        return any(value is not None for value in (
            self.calls, self.prompt_tokens, self.completion_tokens,
            self.tokens, self.wallclock, self.usd))

    @classmethod
    def from_usage(cls, usage: Any, *, usd: Optional[float] = None) -> "Cost":
        """The real counts a provider recorded (``agents.Usage``), plus an estimate."""
        missing = [name for name in ("calls", "prompt_tokens",
                                     "completion_tokens", "seconds")
                   if not hasattr(usage, name)]
        if missing:
            raise TypeError(
                "usage must expose " + ", ".join(missing)
                + " (pass agentdescent.agents.Usage or a metered equivalent)")
        return cls(
            calls=_count(usage.calls, "calls"),
            prompt_tokens=_count(usage.prompt_tokens, "prompt_tokens"),
            completion_tokens=_count(usage.completion_tokens, "completion_tokens"),
            wallclock=float(usage.seconds), usd=usd)

    @classmethod
    def from_cards(cls, cards: Iterable[Any]) -> "Cost":
        """The cost the contributing evidence cards recorded for this diff.

        In-tree this is always unknown: no producer writes ``cost_tokens`` or
        ``cost_wallclock`` onto a card (``evolution.py`` and ``async_evolve.py``
        build cards without them), so the sum is empty and this returns
        ``Cost()`` -- unknown, not free. A caller that wants the gate to price a
        diff passes the measurement as ``MergeContext.diff_cost =
        Cost.from_usage(usage)`` instead of relying on the cards.
        """
        tokens = 0
        wallclock = 0.0
        seen = False
        for card in cards:
            card_tokens = getattr(card, "cost_tokens", 0) or 0
            card_wallclock = getattr(card, "cost_wallclock", 0.0) or 0.0
            tokens += int(card_tokens)
            wallclock += float(card_wallclock)
            if card_tokens or card_wallclock:
                seen = True
        if not seen:
            return cls()
        return cls(tokens=tokens or None, wallclock=wallclock or None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tokens": self.tokens,
            "wallclock": self.wallclock,
            "usd": self.usd,
        }


def cost_efficiency(gain: float, cost: Cost, *,
                    unit: str = "1k_tokens") -> Optional[float]:
    """``quality_per_cost``: held-out delta per 1k tokens or per USD.

    ``None`` when the number cannot be read: non-positive gain (there is nothing
    to price), missing or zero unit, or a malformed input. A caller that wants
    "unknown" and "terrible" kept apart reads ``None``, never ``0.0``.
    """
    if unit not in _UNITS:
        raise ValueError(f"unit must be one of {_UNITS}, got {unit!r}")
    if not isinstance(cost, Cost):
        raise TypeError("cost must be a Cost")
    if isinstance(gain, bool) or not isinstance(gain, (int, float)):
        raise ValueError("gain must be a number")
    gain = float(gain)
    if not math.isfinite(gain):
        raise ValueError("gain must be finite")
    if gain <= 0.0:
        return None
    if unit == "usd":
        return None if not cost.usd else gain / cost.usd
    if not cost.tokens:
        return None
    return gain * 1000.0 / cost.tokens


def cost_status(value: Optional[float], reference: Optional[float], *,
                tolerance: float = 0.05,
                lower_is_better: bool = False) -> str:
    """Classify ``value`` against ``reference``: improved/neutral/regressed/unknown.

    ``value`` is quality per cost by default (higher is better); a caller
    reporting "cost per point" passes ``lower_is_better=True``. ``tolerance`` is
    the dead band, as a fraction, so a 5% wobble is neutral rather than a
    verdict. A missing or non-positive reference is ``unknown``: there is no
    scale to call anything better or worse against.
    """
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
        raise ValueError("tolerance must be a number in [0, 1)")
    tolerance = float(tolerance)
    if not math.isfinite(tolerance) or not 0.0 <= tolerance < 1.0:
        raise ValueError("tolerance must be a number in [0, 1)")
    if value is None or reference is None:
        return UNKNOWN
    try:
        value = float(value)
        reference = float(reference)
    except (TypeError, ValueError):
        return UNKNOWN
    if not math.isfinite(value) or not math.isfinite(reference):
        return UNKNOWN
    if reference <= 0.0:
        return UNKNOWN
    if lower_is_better:
        if value < reference * (1.0 - tolerance):
            return IMPROVED
        if value > reference * (1.0 + tolerance):
            return REGRESSED
        return NEUTRAL
    if value > reference * (1.0 + tolerance):
        return IMPROVED
    if value < reference * (1.0 - tolerance):
        return REGRESSED
    return NEUTRAL


def _spend_text(cost: Cost) -> str:
    """What the diff spent, in the unit it actually measured (#945 review)."""
    if cost.tokens is not None:
        return f"{int(cost.tokens)} tokens"
    if cost.usd is not None:
        return f"${cost.usd:.4f}"
    return "an unmeasured amount of cost"


class CostPolicy:
    """Acceptance wrapper that prices the candidate before committing it.

    Composition, not replacement: ``CostPolicy(inner)`` runs ``inner`` first and
    returns its rejection untouched -- a cost win cannot rescue a candidate the
    quality gate refused. It only has a say on candidates the inner gate already
    accepted, and it has three:

    * ``reference_quality_per_cost``: refuse when the measured efficiency
      regressed against it, even though raw quality rose;
    * ``min_gain_per_1k_tokens``: refuse when efficiency is below an absolute
      floor, measured per 1000 of ``unit`` -- so with ``unit="usd"`` the
      tokens-named floor is a dollars-efficiency floor;
    * ``require_cost``: defer when the cost is not measured, instead of pricing
      an unknown diff at zero.

    ``inner=None`` means the run's configured
    :class:`~agentdescent.defaults.DefaultAcceptance`; :meth:`configure` fills it
    from :class:`~agentdescent.aggregator.AggregatorConfig` the way the
    aggregator fills the default gate.
    """

    def __init__(self, inner: Optional[Any] = None, *,
                 reference_quality_per_cost: Optional[float] = None,
                 min_gain_per_1k_tokens: Optional[float] = None,
                 tolerance: float = 0.05, require_cost: bool = False,
                 unit: str = "1k_tokens") -> None:
        if unit not in _UNITS:
            raise ValueError(f"unit must be one of {_UNITS}, got {unit!r}")
        if reference_quality_per_cost is not None:
            reference_quality_per_cost = _finite(
                reference_quality_per_cost, "reference_quality_per_cost")
            if reference_quality_per_cost <= 0.0:
                raise ValueError(
                    "reference_quality_per_cost must be > 0 (an unknown "
                    "reference is None, not zero)")
        if min_gain_per_1k_tokens is not None:
            min_gain_per_1k_tokens = _finite(
                min_gain_per_1k_tokens, "min_gain_per_1k_tokens")
        if isinstance(require_cost, bool) is False:
            raise TypeError("require_cost must be a bool")
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) \
                or not math.isfinite(float(tolerance)) \
                or not 0.0 <= float(tolerance) < 1.0:
            raise ValueError("tolerance must be a number in [0, 1)")
        self.inner = inner
        self.reference_quality_per_cost = reference_quality_per_cost
        self.min_gain_per_1k_tokens = min_gain_per_1k_tokens
        self.tolerance = float(tolerance)
        self.require_cost = require_cost
        self.unit = unit

    # -- what the aggregator needs to know --------------------------------
    @property
    def needs_probes(self) -> bool:
        return bool(getattr(self.inner, "needs_probes", False))

    def probe_partitions(self) -> Any:
        inner = self._inner()
        partitions = getattr(inner, "probe_partitions", None)
        if partitions is None:
            raise AttributeError(
                f"{type(inner).__name__} has no probe_partitions()")
        return partitions()

    def configure(self, config: Any) -> None:
        """Fill an unset inner gate from the run's config; forward when present."""
        if self.inner is None:
            from .defaults import DefaultAcceptance

            self.inner = DefaultAcceptance.from_config(config)
            return
        configure = getattr(self.inner, "configure", None)
        if configure is not None:
            configure(config)

    def _inner(self) -> Any:
        if self.inner is None:
            raise ValueError(
                "CostPolicy has no inner acceptance policy; pass one or call "
                "configure(config) before accept()")
        return self.inner

    # -- the gate ---------------------------------------------------------
    def accept(self, ctx: MergeContext) -> AcceptDecision:
        decision = self._inner().accept(ctx)
        if not decision.accept:
            return decision
        gain = decision.observed_delta
        if gain == 0.0:
            gain = ctx.rate(ctx.cand_counts) - ctx.rate(ctx.base_counts)
        cost = self._cost(ctx)
        measured = cost_efficiency(gain, cost, unit=self.unit)
        block = self._block(cost, gain)
        if measured is None:
            if self.require_cost:
                return AcceptDecision(
                    False, "cost-unknown",
                    f"the candidate has no measured cost ({self.unit}) or no "
                    "positive gain to price; require_cost is on, so deferring "
                    "instead of treating an unpriced diff as free",
                    observed_delta=gain, defer=True,
                    provenance={"cost": block})
            block["status"] = UNKNOWN
            return self._accepted(decision, block)
        status = (cost_status(measured, self.reference_quality_per_cost,
                              tolerance=self.tolerance)
                  if self.reference_quality_per_cost is not None else UNKNOWN)
        block["status"] = status
        if status == REGRESSED:
            return AcceptDecision(
                False, "cost-regression",
                f"quality {gain:+.3f} on {_spend_text(cost)} is "
                f"{measured:.4g} per {self.unit}, below the reference "
                f"{self.reference_quality_per_cost:.4g} (tolerance "
                f"{self.tolerance:.0%}); the quality gain is not worth its cost",
                observed_delta=gain, provenance={"cost": block})
        if (self.min_gain_per_1k_tokens is not None
                and measured < self.min_gain_per_1k_tokens):
            return AcceptDecision(
                False, "cost-regression",
                f"quality {gain:+.3f} is {measured:.4g} per {self.unit}, below "
                f"the floor {self.min_gain_per_1k_tokens:.4g}; the quality gain "
                "is not worth its cost",
                observed_delta=gain, provenance={"cost": block})
        return self._accepted(decision, block)

    # -- helpers ----------------------------------------------------------
    def _cost(self, ctx: MergeContext) -> Cost:
        measured = getattr(ctx, "diff_cost", None)
        if measured is not None:
            if not isinstance(measured, Cost):
                raise TypeError("MergeContext.diff_cost must be a Cost or None")
            return measured
        diff = ctx.diff
        cards = list(ctx.cards or ())
        if diff is not None:
            ops = set(getattr(diff, "ops", {}) or {})
            cards = [card for card in cards
                     if set(getattr(getattr(card, "diff", None), "ops", {}) or {})
                     & ops]
        return Cost.from_cards(cards)

    def _block(self, cost: Cost, gain: float) -> Dict[str, Any]:
        block = cost.to_dict()
        block["quality_per_1k_tokens"] = cost_efficiency(
            gain, cost, unit="1k_tokens")
        block["quality_per_usd"] = cost_efficiency(gain, cost, unit="usd")
        block["status"] = UNKNOWN
        block["unit"] = self.unit
        return block

    @staticmethod
    def _accepted(decision: AcceptDecision, block: Dict[str, Any]
                  ) -> AcceptDecision:
        provenance = dict(decision.provenance or {})
        provenance["cost"] = block
        return AcceptDecision(
            True, decision.category, decision.detail,
            p_improve=decision.p_improve,
            observed_delta=decision.observed_delta, defer=decision.defer,
            provenance=provenance)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostReport:
    """Cost per accepted diff and per point of gain, from decision records."""

    decisions: int = 0
    accepted: int = 0
    calls: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    tokens: Optional[int] = None
    wallclock: Optional[float] = None
    usd: Optional[float] = None
    calls_per_accepted: Optional[float] = None
    tokens_per_accepted: Optional[float] = None
    usd_per_accepted: Optional[float] = None
    tokens_per_point: Optional[float] = None
    usd_per_point: Optional[float] = None
    cost_status: str = UNKNOWN
    missing_cost: int = 0
    reference_tokens_per_point: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decisions": self.decisions, "accepted": self.accepted,
            "calls": self.calls, "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tokens": self.tokens, "wallclock": self.wallclock,
            "usd": self.usd,
            "calls_per_accepted": self.calls_per_accepted,
            "tokens_per_accepted": self.tokens_per_accepted,
            "usd_per_accepted": self.usd_per_accepted,
            "tokens_per_point": self.tokens_per_point,
            "usd_per_point": self.usd_per_point,
            "cost_status": self.cost_status,
            "missing_cost": self.missing_cost,
            "reference_tokens_per_point": self.reference_tokens_per_point,
        }


def _row_cost(row: Any, index: int) -> Optional[Cost]:
    """Read a record's ``cost`` as a Cost, or None when it carries none."""
    raw = row.get("cost") if isinstance(row, Mapping) else getattr(
        row, "cost", None)
    if raw is None:
        return None
    if isinstance(raw, Cost):
        return raw if raw.known else None
    if not (isinstance(raw, Mapping)
            or any(hasattr(raw, key) for key in (
                "calls", "prompt_tokens", "completion_tokens", "tokens",
                "wallclock", "usd"))):
        raise ValueError(
            f"record {index}: cost must be a Cost, a mapping or an object "
            "with cost fields")
    values = {key: (raw.get(key) if isinstance(raw, Mapping)
                    else getattr(raw, key, None))
              for key in ("calls", "prompt_tokens", "completion_tokens",
                          "tokens", "wallclock", "usd")}
    cost = Cost(**values)
    return cost if cost.known else None


def _row_gain(row: Any, index: int) -> Optional[float]:
    raw = row.get("gain") if isinstance(row, Mapping) else getattr(
        row, "gain", None)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"record {index}: gain must be a number or None")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"record {index}: gain must be finite")
    return value


def cost_report(records: Iterable[Any], *,
                reference_tokens_per_point: Optional[float] = None,
                tolerance: float = 0.05) -> CostReport:
    """Aggregate per-decision records into the report the issue asks for.

    Each record is a mapping/object with ``accepted`` (bool), an optional
    ``gain`` (held-out delta) and an optional ``cost``. Missing cost is counted
    in ``missing_cost`` and leaves the derived fields ``None`` -- never ``0``.
    ``cost_status`` compares ``tokens_per_point`` with
    ``reference_tokens_per_point`` (lower is better); with no reference or no
    priced accepted diff it is ``unknown``.

    A derived read is per **unit**, not per row: ``usd_per_accepted`` needs
    every decision to have measured ``usd``, ``tokens_per_accepted`` needs
    ``tokens`` on every one of them, and the same holds for ``calls`` and for
    the per-point reads (``usd`` is optional by design and ``from_cards`` never
    records ``calls``, so a row priced in one unit is normal). A row that is
    priced but lacks the unit would otherwise enter the amortization as a free
    contribution in that unit and make the diff read cheaper than the evidence
    -- the failure the all-unpriced rule was for, one field down.
    """
    rows = list(records)
    accepted = 0
    missing = 0
    totals = {name: 0 for name in (
        "calls", "prompt_tokens", "completion_tokens", "tokens")}
    wallclock = 0.0
    usd = 0.0
    seen = set()
    gain_sum = 0.0
    # Per unit: does every decision measure it? The amortized reads divide total
    # spend by accepted diffs, so a rejected decision that never priced itself
    # understates the numerator exactly as an accepted one does.
    measured = {"calls": True, "tokens": True, "usd": True}
    for index, row in enumerate(rows):
        flag = row.get("accepted") if isinstance(row, Mapping) else getattr(
            row, "accepted", None)
        if not isinstance(flag, bool):
            raise ValueError(f"record {index}: accepted must be a bool")
        cost = _row_cost(row, index)
        if cost is None:
            for name in measured:
                measured[name] = False
        else:
            for name in measured:
                if getattr(cost, name) is None:
                    measured[name] = False
        if flag:
            accepted += 1
            gain = _row_gain(row, index)
            if gain is not None and gain > 0.0:
                gain_sum += gain
            if cost is None:
                missing += 1
        if cost is None:
            continue
        for name in totals:
            value = getattr(cost, name)
            if value is not None:
                totals[name] += value
                seen.add(name)
        if cost.wallclock is not None:
            wallclock += cost.wallclock
            seen.add("wallclock")
        if cost.usd is not None:
            usd += cost.usd
            seen.add("usd")

    calls = int(totals["calls"]) if "calls" in seen else None
    prompt = int(totals["prompt_tokens"]) if "prompt_tokens" in seen else None
    completion = (int(totals["completion_tokens"])
                  if "completion_tokens" in seen else None)
    tokens = int(totals["tokens"]) if "tokens" in seen else None
    wall = wallclock if "wallclock" in seen else None
    dollars = usd if "usd" in seen else None

    # A partial numerator over a full denominator reads as a cheaper diff: an
    # unpriced decision understates the spend the amortized reads divide, and a
    # priced row that simply did not measure this unit is a free contribution in
    # it. Both are the same failure, so each derived read needs its own unit
    # complete over **every** decision -- the numerator is total spend, not
    # accepted spend -- while the denominator stays the accepted diffs. The
    # totals remain partial and `missing_cost` says how many accepted diffs
    # carry no cost at all (#945 review).
    def _per(value: Optional[float], unit: str) -> Optional[float]:
        if not measured[unit] or value is None or accepted <= 0:
            return None
        return value / accepted

    tokens_per_point = (None if not measured["tokens"] or tokens is None
                        or gain_sum <= 0.0 else tokens / gain_sum)
    usd_per_point = (None if not measured["usd"] or dollars is None
                     or gain_sum <= 0.0 else dollars / gain_sum)
    status = UNKNOWN
    if reference_tokens_per_point is not None and tokens_per_point is not None:
        status = cost_status(tokens_per_point, reference_tokens_per_point,
                             tolerance=tolerance, lower_is_better=True)
    return CostReport(
        decisions=len(rows), accepted=accepted, calls=calls,
        prompt_tokens=prompt, completion_tokens=completion, tokens=tokens,
        wallclock=wall, usd=dollars,
        calls_per_accepted=_per(calls, "calls"),
        tokens_per_accepted=_per(tokens, "tokens"),
        usd_per_accepted=_per(dollars, "usd"),
        tokens_per_point=tokens_per_point, usd_per_point=usd_per_point,
        cost_status=status, missing_cost=missing,
        reference_tokens_per_point=reference_tokens_per_point)
