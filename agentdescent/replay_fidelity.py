"""What a captured run can and cannot reconstruct.

Two runs can share a ``RunManifest`` and still diverge: the RNG state, the
harness's own hidden state and the environment (interpreter, tool versions, cwd,
environment variable values) are not manifest inputs. A replay or counterfactual
claim made from such a record therefore overstates what is reconstructible, and a
"same run" comparison can silently change the environment underneath the score.

This module records what the missing inputs looked like and names what it could
not capture:

* :class:`EnvironmentFingerprint` -- cwd, interpreter and OS, tool versions, and
  the sorted **names** of an allowlisted set of environment variables
  (:data:`REPLAY_ENV_ALLOWLIST`) that were present plus how many there were; no
  value is read at all, so none can be stored or confirmed against a candidate,
  and a name that looks secret is refused even when a caller asks for it;
* :class:`RngRecord` -- one seed/state digest per interaction boundary, built by
  :func:`rng_digest`, which refuses to invent a digest when it is given neither;
* :class:`ReplayFidelity` -- the two plus hidden-state digests and the list of
  sources that could not be captured. ``eligible`` is true only when a boundary
  digest, an environment fingerprint and hidden-state coverage all exist and
  nothing was left uncaptured;
* :func:`replay_check` -- compares a captured run with its replay, refusing the
  comparison outright when either side is not replay-eligible.

The rule is: a claim is scoped to what was captured. ``RunManifest`` carries
``replay_eligible`` / ``replay_notes`` so a consumer refuses instead of guessing,
and ``agentdescent.counterfactual.ReplayLab`` refuses a counterfactual over an
ineligible manifest, naming what was not reconstructed.

Everything here is metadata: digests and names, never values, transcripts or
prompts. A field that must hold a digest is validated as a 64-character sha256,
so raw content cannot be pasted into the record by accident.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform as _platform
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

__all__ = [
    "REPLAY_ENV_ALLOWLIST",
    "EnvironmentFingerprint",
    "ReplayCheck",
    "ReplayFidelity",
    "ReplayNotEligible",
    "RngRecord",
    "content_digest",
    "replay_check",
    "rng_digest",
]

#: Environment variable names whose **presence** may affect a run, and which are
#: therefore recorded as names. Chosen for determinism, not convenience: the
#: hash seed changes dict/set iteration, ``PYTHONPATH`` decides which code is
#: imported at all, the locale changes sorting and number formatting, ``TZ``
#: changes timestamps a prompt may contain, and the thread counts change
#: floating-point reduction order in numeric workloads.
#:
#: Names only, never values -- not even hashed (Security review, #952). A
#: four-entry dictionary recovered a ``TZ`` value offline from the old sha256
#: digests, and any candidate value confirms by ``sha256()``, so a digest of a
#: value is value material. :meth:`EnvironmentFingerprint.capture` also
#: intersects the caller's list with this tuple, so no caller can widen it, and
#: still drops credential-shaped names.
REPLAY_ENV_ALLOWLIST: Tuple[str, ...] = (
    "LANG",
    "LC_ALL",
    "OMP_NUM_THREADS",
    "PYTHONHASHSEED",
    "PYTHONPATH",
    "TZ",
)

#: Name-shaped credential guard. Deliberately broader than the allowlist check:
#: a name that could hold a secret is dropped before its value is read.
_SECRET_NAME = re.compile(r"(token|key|secret|password|credential|auth)", re.I)

_HASH = re.compile(r"[0-9a-f]{64}")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=str, ensure_ascii=True)


def content_digest(value: Any) -> str:
    """A sha256 digest of any JSON-able summary.

    What a hidden-state source (a tool's cursor, a sandbox's session id, a
    provider's cache key) may be recorded as: the digest lands in the record, the
    value does not.
    """
    return _sha(_canonical(value))


def rng_digest(*, seed: Any = None, state: Any = None) -> str:
    """A digest of an RNG seed and/or a state summary at one boundary.

    Both arguments are optional individually but not together: a harness that
    exposes neither is *not replayable*, and this raises instead of recording a
    digest of nothing, which would read as "captured" to every consumer.
    """
    if seed is None and state is None:
        raise ValueError(
            "an RNG digest needs a seed or a state summary; a harness that "
            "exposes neither is not replayable and must be named as uncaptured")
    return _sha(_canonical({"seed": seed, "state": state}))


def _digest_field(value: Any, label: str) -> str:
    """Validate that ``value`` is a sha256 hex digest, never raw content."""
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(
            f"{label} must be a sha256 hex digest (64 lowercase hex chars), got "
            f"{type(value).__name__}: digests only, never raw content")
    return value


def _names(names: Iterable[str]) -> Tuple[str, ...]:
    """The allowlist, minus anything credential-shaped, sorted and unique.

    The intersection is the point: a caller may narrow the set (pass one name)
    but never widen it, so ``capture(env={"SESSION": tok}, env_names=("SESSION",))``
    drops the name instead of recording anything derived from the token.
    """
    allowed = set(REPLAY_ENV_ALLOWLIST)
    cleaned = {n for n in names
               if isinstance(n, str) and n in allowed
               and not _SECRET_NAME.search(n)}
    return tuple(sorted(cleaned))


@dataclass(frozen=True)
class EnvironmentFingerprint:
    """The environment a run happened in, as far as it is safe to record it.

    ``env_names`` is the sorted allowlist of variables that were **present**,
    and ``env_count`` is how many there were (Security review, #952: names and a
    count, never values, hashed or otherwise). ``missing_env`` names allowlisted
    variables that were unset, so two shells that differ only by an absent
    variable are still distinguishable. Tool versions are the caller's claim (the
    engine does not shell out): pass the versions it actually resolved.
    """

    cwd: str
    python: str
    platform: str
    tools: Mapping[str, str] = field(default_factory=dict)
    env_names: Tuple[str, ...] = ()
    missing_env: Tuple[str, ...] = ()

    @property
    def env_count(self) -> int:
        """How many allowlisted variables were present."""
        return len(self.env_names)

    @classmethod
    def capture(
        cls,
        *,
        cwd: Optional[str] = None,
        tools: Optional[Mapping[str, str]] = None,
        env: Optional[Mapping[str, str]] = None,
        env_names: Sequence[str] = REPLAY_ENV_ALLOWLIST,
        platform_string: Optional[str] = None,
        python: Optional[str] = None,
    ) -> "EnvironmentFingerprint":
        """Fingerprint this process (or the explicit values a caller supplies)."""
        environ = os.environ if env is None else env
        present = []
        missing = []
        for name in _names(env_names):
            # Presence only: the value is never read, so it cannot be stored,
            # hashed into a recoverable digest, or confirmed against a candidate.
            (present if name in environ else missing).append(name)
        return cls(
            cwd=os.path.abspath(cwd if cwd is not None else os.getcwd()),
            python=python if python is not None else _platform.python_version(),
            platform=(platform_string if platform_string is not None
                      else _platform.platform()),
            tools=dict(tools or {}),
            env_names=tuple(present),
            missing_env=tuple(missing),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cwd": self.cwd,
            "python": self.python,
            "platform": self.platform,
            "tools": dict(self.tools),
            "env_names": list(self.env_names),
            "env_count": self.env_count,
            "missing_env": list(self.missing_env),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "EnvironmentFingerprint":
        return cls(
            cwd=str(d.get("cwd", "")),
            python=str(d.get("python", "")),
            platform=str(d.get("platform", "")),
            tools=dict(d.get("tools") or {}),
            env_names=tuple(d.get("env_names") or ()),
            missing_env=tuple(d.get("missing_env") or ()),
        )

    def diff(self, other: "EnvironmentFingerprint") -> Tuple[str, ...]:
        """Names of the environment inputs that differ (empty when identical)."""
        changed = []
        for name in ("cwd", "python", "platform"):
            if getattr(self, name) != getattr(other, name):
                changed.append(f"environment:{name}")
        for tool in sorted(set(self.tools) | set(other.tools)):
            if self.tools.get(tool) != other.tools.get(tool):
                changed.append(f"environment:tool:{tool}")
        if self.env_count != other.env_count:
            changed.append("environment:env_count")
        for var in sorted(set(self.env_names) ^ set(other.env_names)):
            changed.append(f"environment:env:{var}")
        for var in sorted(set(self.missing_env) | set(other.missing_env)):
            if (var in self.missing_env) != (var in other.missing_env):
                changed.append(f"environment:missing:{var}")
        return tuple(changed)


@dataclass(frozen=True)
class RngRecord:
    """One RNG seed/state digest at an interaction boundary.

    ``boundary`` names where it was taken (``"start"``, ``"interaction:3"``,
    ``"end"``); ``seed`` is the seed as recorded when the harness exposes one.
    The digest is what comparisons use: the state itself is never stored.
    """

    boundary: str
    digest: str
    seed: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.boundary, str) or not self.boundary.strip():
            raise ValueError("RngRecord.boundary must be a non-empty string")
        _digest_field(self.digest, "RngRecord.digest")

    def to_dict(self) -> Dict[str, Any]:
        return {"boundary": self.boundary, "digest": self.digest, "seed": self.seed}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "RngRecord":
        return cls(boundary=str(d["boundary"]), digest=str(d["digest"]),
                   seed=None if d.get("seed") is None else str(d["seed"]))


@dataclass(frozen=True)
class ReplayFidelity:
    """Everything a replay needs that the manifest's input hashes do not cover.

    ``eligible`` is the only claim this record makes, and it is deliberately
    narrow: an environment fingerprint, at least one RNG boundary digest, and
    **nothing** named as uncaptured. ``uncaptured`` is how a harness says "I have
    hidden state nobody can observe" -- an empty tuple is the caller asserting
    that every source it knows of was captured, not that it looked and found
    none.
    """

    environment: Optional[EnvironmentFingerprint] = None
    rng: Tuple[RngRecord, ...] = ()
    hidden_state: Mapping[str, str] = field(default_factory=dict)
    uncaptured: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for source, digest in self.hidden_state.items():
            _digest_field(digest, f"hidden_state[{source!r}]")

    @classmethod
    def capture(
        cls,
        *,
        environment: Optional[EnvironmentFingerprint] = None,
        rng: Iterable[RngRecord] = (),
        hidden_state: Optional[Mapping[str, Any]] = None,
        uncaptured: Iterable[str] = (),
    ) -> "ReplayFidelity":
        """Assemble a record; hidden-state summaries are digested here.

        ``hidden_state`` values may be any JSON-able summary -- they are run
        through :func:`content_digest`, so a caller can pass a tool's session id
        or cursor without thinking about it and the digest is still all that is
        stored.
        """
        return cls(
            environment=environment,
            rng=tuple(rng),
            hidden_state={str(k): (v if isinstance(v, str) and _HASH.fullmatch(v)
                                   else content_digest(v))
                          for k, v in (hidden_state or {}).items()},
            uncaptured=tuple(str(u) for u in uncaptured),
        )

    @property
    def eligible(self) -> bool:
        return (self.environment is not None and bool(self.rng)
                and not self.uncaptured)

    def notes(self) -> Tuple[str, ...]:
        """What would stop a replay claim, in words (empty when eligible)."""
        out = []
        if self.environment is None:
            out.append("environment: not captured (cwd, tool versions and "
                       "allowlisted env names are missing)")
        if not self.rng:
            out.append("rng: no interaction-boundary seed/state digest was recorded")
        out.extend(self.uncaptured)
        return tuple(out)

    def diff(self, other: "ReplayFidelity") -> Tuple[str, ...]:
        """Names of the recorded inputs that differ (empty for the same run)."""
        changed = []
        if (self.environment is None) != (other.environment is None):
            changed.append("environment")
        elif self.environment is not None and other.environment is not None:
            changed.extend(self.environment.diff(other.environment))
        mine = {r.boundary: r.digest for r in self.rng}
        theirs = {r.boundary: r.digest for r in other.rng}
        for boundary in sorted(set(mine) | set(theirs)):
            if mine.get(boundary) != theirs.get(boundary):
                changed.append(f"rng:{boundary}")
        for source in sorted(set(self.hidden_state) | set(other.hidden_state)):
            if self.hidden_state.get(source) != other.hidden_state.get(source):
                changed.append(f"hidden_state:{source}")
        return tuple(changed)

    def matches(self, other: "ReplayFidelity") -> bool:
        return not self.diff(other)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": (None if self.environment is None
                            else self.environment.to_dict()),
            "rng": [r.to_dict() for r in self.rng],
            "hidden_state": dict(self.hidden_state),
            "uncaptured": list(self.uncaptured),
            "eligible": self.eligible,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ReplayFidelity":
        environment = d.get("environment")
        return cls(
            environment=(None if environment is None
                         else EnvironmentFingerprint.from_dict(environment)),
            rng=tuple(RngRecord.from_dict(r) for r in d.get("rng") or ()),
            hidden_state=dict(d.get("hidden_state") or {}),
            uncaptured=tuple(d.get("uncaptured") or ()),
        )


class ReplayNotEligible(RuntimeError):
    """A counterfactual was asked for over a run that cannot be replayed.

    ``notes`` is the manifest's ``replay_notes``: the sources that were not
    reconstructed, so a caller can report *why* rather than a bare refusal.
    """

    def __init__(self, notes: Iterable[str]) -> None:
        self.notes: Tuple[str, ...] = tuple(str(n) for n in notes)
        detail = "; ".join(self.notes) or "no reason was recorded"
        super().__init__(
            "replay_eligible is false, so this counterfactual would be a guess "
            f"rather than a reconstruction; not reconstructed: {detail}")


@dataclass(frozen=True)
class ReplayCheck:
    """The result of comparing a captured run with its replay."""

    ok: bool
    changed: Tuple[str, ...] = ()
    verdict_changed: bool = False
    notes: Tuple[str, ...] = ()


def _event_signature(trajectory: Any) -> Tuple[Tuple[str, str, int], ...]:
    return tuple((getattr(e, "kind", ""), getattr(e, "source", ""),
                  int(getattr(e, "cost_tokens", 0)))
                 for e in (getattr(trajectory, "events", ()) or ()))


def replay_check(captured: Any, replayed: Any) -> ReplayCheck:
    """Whether ``replayed`` reproduces ``captured`` -- or refuses to say.

    Takes two trajectory-like objects (anything with ``replay``, ``reward``,
    ``output`` and ``events``; :class:`agentdescent.trajectory.Trajectory` is the
    one this module is written for). A side that is not replay-eligible can never
    produce ``ok=True``: the honest answer is "not reconstructed", with the
    recorded reasons, not a comparison of two scores taken in different
    environments.
    """
    captured_notes = tuple(getattr(captured, "replay_notes", ()) or ())
    replayed_notes = tuple(getattr(replayed, "replay_notes", ()) or ())
    if not getattr(captured, "replay_eligible", False):
        return ReplayCheck(ok=False, notes=captured_notes)
    if not getattr(replayed, "replay_eligible", False):
        return ReplayCheck(ok=False, notes=replayed_notes)
    changed = list(captured.replay.diff(replayed.replay))
    verdict_changed = (captured.reward != replayed.reward
                       or captured.output != replayed.output)
    if not verdict_changed and _event_signature(captured) != _event_signature(replayed):
        changed.append("events")
        verdict_changed = True
    return ReplayCheck(ok=not changed and not verdict_changed,
                       changed=tuple(changed), verdict_changed=verdict_changed)
