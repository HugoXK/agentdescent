"""What a verifier admitted, what it rejected, and what the oracle says (#940).

Auditing only accepted commits measures precision and nothing else -- a verifier
that rejects everything measures 1.0. This report adds the rejected stratum.

``n_accepted`` and ``n_rejected`` are the verifier's own decisions (the inner
policy, then the verifier's sample). The audit does not move a commit from one
stratum to the other: it labels the decision. Otherwise a verifier whose accepted
commits the oracle denies could raise its own precision by denying them at audit
time, which is the bias this module exists to remove.

Means hide a second failure: a verifier can agree on the average while being
wrong *the same way* under every prompt. ``repeat_overlap`` measures that -- the
share of prompts on which an audited accepted error recurs -- and a high one
blocks an admit the averages alone would allow (#940).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .audit.estimate import bootstrap_ci

__all__ = ["AdmissionReport", "admission_report"]

CONFIRM_BAR = 0.8   # admit only from here, and only on the pessimistic bound
DEMOTE_BAR = 0.5    # every reject needs a bound already under this
MIN_AUDITED = 3     # below this a stratum is "not enough evidence", not a verdict
UNIVERSALITY_BAR = 0.5   # mean share of prompts a recurring accepted error hits
MIN_PROMPTS = 2          # one prompt cannot overlap with itself


@dataclass(frozen=True)
class AdmissionReport:
    """Both strata of one verifier's decisions, with the bounds that decided it.

    ``precision``: share of the audited accepted commits whose gain the oracle
    confirms, with ``precision_lower``/``precision_upper`` its bootstrap interval.
    ``rejection_accuracy_lower``/``_upper``: interval on the share of the
    verifier's rejections that were correct -- the complement of the share of
    rejected commits that were in fact good, so a higher number is better.

    ``None`` means "not audited"; it is never read as "perfect". A wide interval
    is "not enough evidence yet", and only a bound already on the wrong side of a
    bar demotes a verifier, so one or two audited rejections can never fail a
    promotion closed.

    ``repeat_overlap``: mean share of prompts on which an audited accepted error
    recurs -- the verifier claiming a gain the oracle denies for the same commit
    under different prompts. ``high_universality`` is that share at or above
    :data:`UNIVERSALITY_BAR` with at least :data:`MIN_AUDITED` audited accepts,
    and it blocks an admit: shared errors are one systemic failure, not the noise
    precision already averages away. ``repeat_overlap is None`` means
    unmeasurable (fewer than two prompts, or fewer than three audited accepts) and
    is never read as "no shared error"; it does not move the verdict either way.
    """

    n_accepted: int
    n_rejected: int
    precision: Optional[float]
    precision_lower: Optional[float]
    precision_upper: Optional[float]
    rejection_accuracy_lower: Optional[float]
    rejection_accuracy_upper: Optional[float]
    recommendation: str = "defer"
    reason: str = ""
    repeat_overlap: Optional[float] = None
    high_universality: bool = False


def _interval(values: Sequence[float], probabilities: Sequence[float], seed: int):
    """Bootstrap interval, or ``(None, None)`` below two audited units."""
    lower, upper = bootstrap_ci(list(values), list(probabilities), seed=seed)
    if lower != lower or upper != upper:        # NaN: fewer than two units
        return None, None
    return float(lower), float(upper)


def _show(lower: Optional[float], upper: Optional[float]) -> str:
    if lower is None or upper is None:
        return "not yet bounded"
    return f"{lower:.3f}..{upper:.3f}"


def admission_report(*, n_accepted: int, n_rejected: int,
                     accepted_confirmed: Sequence[float],
                     rejected_good: Sequence[float],
                     rejected_sample_rate: float, seed: int = 0,
                     accepted_error_overlap: Sequence[float] = (),
                     prompts: int = 0
                     ) -> AdmissionReport:
    """Label both strata; one ``1.0``/``0.0`` per audited decision.

    ``accepted_confirmed``: one entry per audited accepted commit, ``1.0`` when
    the oracle confirms the gain.
    ``rejected_good``: one entry per audited rejected commit, ``1.0`` when the
    commit was in fact good -- i.e. the verifier threw good work away.
    ``accepted_error_overlap``: one entry per audited accepted commit, the share
    of the ``prompts`` audit tasks on which the verifier claimed a gain the
    oracle denies. ``prompts`` is how many prompts the audit set has; below
    :data:`MIN_PROMPTS` the overlap cannot be measured and stays ``None``.

    Bars: demote only on a bound already under 0.5, admit only with both
    pessimistic bounds at 0.8, and defer otherwise -- including when an interval
    is still too wide to say either. A high cross-prompt error overlap also
    defers: it is the same failure recurring, so the averages are not the whole
    story (#940).
    """
    confirmed = [float(value) for value in accepted_confirmed]
    precision = (sum(confirmed) / len(confirmed)) if confirmed else None
    p_lower, p_upper = _interval(confirmed, [1.0] * len(confirmed), seed)

    good = [float(value) for value in rejected_good]
    # One inclusion probability for every unit: the Hajek weights cancel and an
    # unweighted mean would be the same number. Kept weighted because the rate
    # can become stratified later, and a raw mean would then be quietly wrong.
    probs = [rejected_sample_rate or 1.0] * len(good)
    g_lower, g_upper = _interval(good, probs, seed)
    # A rejection is correct when the commit it dropped was not good, so the
    # accuracy interval is the complement of the "was good" interval, reversed.
    r_lower = None if g_upper is None else max(0.0, 1.0 - g_upper)
    r_upper = None if g_lower is None else min(1.0, 1.0 - g_lower)

    # Cross-prompt overlap (#940): a mean gain hides an error that recurs on
    # every prompt, so the accepted stratum also reports the share of prompts
    # each audited error hits. Unmeasurable is None, never 0.0.
    overlaps = [float(value) for value in accepted_error_overlap]
    repeat_overlap = None
    if prompts >= MIN_PROMPTS and len(overlaps) >= MIN_AUDITED:
        repeat_overlap = sum(overlaps) / len(overlaps)
    high_universality = (repeat_overlap is not None
                         and repeat_overlap >= UNIVERSALITY_BAR)

    def report(verdict: str, reason: str) -> AdmissionReport:
        return AdmissionReport(n_accepted, n_rejected, precision,
                               p_lower, p_upper, r_lower, r_upper,
                               verdict, reason, repeat_overlap,
                               high_universality)

    enough_accepted = len(confirmed) >= MIN_AUDITED
    enough_rejected = len(good) >= MIN_AUDITED

    # Decisive first: a verifier that fails a stratum is demoted whether or not
    # the other stratum has been audited yet.
    wrong = []
    if enough_accepted and p_upper is not None and p_upper < DEMOTE_BAR:
        wrong.append(f"precision {precision:.3f} (at most {p_upper:.3f}): "
                     f"the oracle denies what it accepts")
    if enough_rejected and r_upper is not None and r_upper < DEMOTE_BAR:
        wrong.append(f"rejections correct at most {r_upper:.3f}: rejects good work")
    if wrong:
        return report("reject", "; ".join(wrong))

    if precision is None and not good:
        return report("defer", "admission is incomplete: neither stratum was audited")
    if precision is None:
        return report("defer", "admission is incomplete: no accepted commit was audited")
    if not good:
        return report("defer", "admission is incomplete: no rejection was audited")

    # A recurring error is a systemic failure the averages hide, so it blocks an
    # admit but never demotes on its own: it says what kind of error this is, not
    # how often -- frequency is what the precision bar already measures.
    if high_universality:
        return report("defer",
                      f"cross-prompt error overlap {repeat_overlap:.3f} over "
                      f"{len(overlaps)} audited accepts on {prompts} prompts: "
                      f"wrong the same way under different prompts")

    if (enough_accepted and enough_rejected
            and p_lower is not None and r_lower is not None
            and p_lower >= CONFIRM_BAR and r_lower >= CONFIRM_BAR):
        return report("admit", f"precision >= {p_lower:.3f}, "
                               f"rejections correct >= {r_lower:.3f}")
    return report("defer", f"insufficient evidence: {len(confirmed)} audited accepts "
                           f"(precision {_show(p_lower, p_upper)}), {len(good)} audited "
                           f"rejections (correct {_show(r_lower, r_upper)})")
