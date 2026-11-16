"""Shared plumbing for the product surfaces (CLI + MCP).

The four P1 surfaces (`platform`, `capability`, `ops`, `experience`) all need
the same small things: a schema version, a fail-closed input error, JSON/JSONL
loading, atomic output, and a ``module:attribute`` ref resolver with a message
that names the ref. Keeping them here means the commands cannot drift on the
envelope or on how a bad file is reported.

This module is not a public API; it is imported by the surface modules and by
``cli``/``mcp``. It deliberately has no top-level package export.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import tempfile
from typing import (Any, Dict, Iterator, Mapping, Optional, Sequence, Tuple,
                    Type, TypeVar)

__all__ = [
    "SURFACE_SCHEMA_VERSION",
    "SurfaceError",
    "atomic_write_json",
    "atomic_write_text",
    "load_json",
    "load_jsonl",
    "parse_csv",
    "parse_floats",
    "parse_ints",
    "require_callable",
    "require_instance",
    "require_mapping",
    "require_text",
    "ensure_write_path",
    "resolve_builder",
    "resolve_ref",
    "surface_allow_from_env",
    "surface_write_dirs_from_env",
    "scrub_host_env",
    "SESSION_MARKERS",
    "DETACHED_KEEP_VARS",
    "is_session_marker",
]

SURFACE_SCHEMA_VERSION = 1
T = TypeVar("T")


class SurfaceError(ValueError):
    """An input the surface cannot use; the message is safe to print."""


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise SurfaceError(f"{name} must be a string")
    if not value.strip():
        raise SurfaceError(f"{name} must be a non-empty string")
    return value


def require_mapping(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SurfaceError(f"{name} must be a JSON object")
    return dict(value)


def require_callable(value: Any, name: str) -> Any:
    if not callable(value):
        raise SurfaceError(f"{name} must be callable")
    return value


def require_instance(value: Any, cls: Type[T], name: str) -> T:
    if not isinstance(value, cls):
        raise SurfaceError(
            f"{name} must be {cls.__name__}, got {type(value).__name__}")
    return value


def _path(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SurfaceError(f"{name} must be a non-empty path")
    return os.path.abspath(os.path.expanduser(value))


def load_json(value: Any, *, name: str) -> Any:
    """A JSON object/array from a path or an inline mapping/sequence."""
    if isinstance(value, (Mapping, list, tuple)):
        return value
    path = _path(value, name)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as error:
        raise SurfaceError(f"{name} {value!r} cannot be read: {error}") from None
    except ValueError as error:
        raise SurfaceError(f"{name} {value!r} is not valid JSON: {error}") from None


def load_jsonl(value: Any, *, name: str) -> Iterator[Dict[str, Any]]:
    """One JSON object per line, or a JSON array of objects."""
    if isinstance(value, list):
        rows = value
    else:
        path = _path(value, name)
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as error:
            raise SurfaceError(f"{name} {value!r} cannot be read: {error}") from None
        stripped = text.strip()
        if not stripped:
            return iter(())
        if stripped.startswith("["):
            try:
                rows = json.loads(stripped)
            except ValueError as error:
                raise SurfaceError(
                    f"{name} {value!r} is not valid JSON: {error}") from None
            if not isinstance(rows, list):
                raise SurfaceError(f"{name} must be a JSON array")
        else:
            rows = []
            for line_no, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as error:
                    raise SurfaceError(
                        f"{name} line {line_no} is not valid JSON: {error}"
                    ) from None
                if not isinstance(row, Mapping):
                    raise SurfaceError(
                        f"{name} line {line_no} must be a JSON object")
                rows.append(dict(row))
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise SurfaceError(f"{name}[{index}] must be a JSON object")
        yield dict(row)


def atomic_write_text(path: str, text: str) -> str:
    """Write text atomically; returns the absolute path."""
    resolved = os.path.abspath(os.path.expanduser(path))
    if os.path.islink(resolved):
        # The operator's link is not this writer's to destroy: `os.replace` does
        # not follow the final symlink, so the target keeps its bytes but the
        # link is swapped for a regular file without a word -- while init,
        # apply and demo refuse the same shape at exit 2 (#1008/#1020/#1021).
        # Only the leaf is checked, so a symlinked directory above it still
        # resolves as it does today (#1029).
        raise SurfaceError(
            f"cannot write {resolved}: {os.path.basename(resolved)!r} "
            f"is a symlink")
    directory = os.path.dirname(resolved)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".agentdescent-surface-", dir=directory, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return resolved


def atomic_write_json(path: str, payload: Any) -> str:
    """Write ``payload`` as pretty JSON, atomically; returns the absolute path."""
    return atomic_write_text(
        path, json.dumps(payload, indent=2, sort_keys=True,
                         ensure_ascii=False, default=str) + "\n")


def surface_allow_from_env(environ: Optional[Mapping[str, str]] = None
                            ) -> tuple:
    """The operator's ref allowlist for the MCP surfaces (empty = refuse)."""
    raw = (environ if environ is not None else os.environ).get(
        "AGENTDESCENT_SURFACE_ALLOW", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def surface_write_dirs_from_env(environ: Optional[Mapping[str, str]] = None
                                 ) -> tuple:
    """The operator's write-directory allowlist for the MCP surfaces.

    Unset defaults to the server's cwd and ``$AGENTDESCENT_HOME``; an empty
    value refuses every MCP write path.
    """
    env = environ if environ is not None else os.environ
    raw = env.get("AGENTDESCENT_SURFACE_WRITE_DIRS")
    if raw is None:
        home = env.get("AGENTDESCENT_HOME") or "~/.agentdescent"
        return (os.getcwd(), os.path.abspath(os.path.expanduser(home)))
    return tuple(part.strip() for part in raw.split(",") if part.strip())


#: Environment variables a host agent sets in its own session and its children
#: inherit. A worker that sees them believes it is *inside* that session: Claude
#: Code refuses to start, DSH loads the parent's profile, and a worker whose
#: host runs this package's MCP server would call it recursively (#1082).
#:
#: One tuple, in this leaf module, because there used to be two lists: the
#: candidate worker (:func:`agentdescent.agents.worker_env`) dropped these
#: eleven names while :func:`scrub_host_env` dropped the four prefixes
#: ``DSH_``/``CLAUDE``/``CODEX``/``MCP_``. Measured on that pair, five of the
#: eleven crossed the scrub -- ``OPENAI_AGENT_*``, ``OPENCODE_CONFIG``,
#: ``OPENCODE_CONFIG_CONTENT``, ``OPENCODE_CONFIG_DIR`` and ``XDG_CONFIG_HOME``
#: -- and the two OpenCode config carriers are the ones measured to hand a
#: nested process the parent's MCP servers. The tuple lives here rather than in
#: ``agents`` because ``agents`` imports ``socket``/``threading``/``urllib``
#: and every surface module imports this one.
SESSION_MARKERS: Tuple[str, ...] = (
    "CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_CONFIG_DIR", "CODEX_", "DSH_",
    "OPENAI_AGENT_", "MCP_",
    # OpenCode reads three of these, and redirecting only the directory is not
    # isolation: `OPENCODE_CONFIG` (a file) and `OPENCODE_CONFIG_CONTENT`
    # (inline JSON) both win over `OPENCODE_CONFIG_DIR` -- measured, a config
    # named by `OPENCODE_CONFIG` still supplied its MCP servers with the dir
    # pointed at an empty directory. They are dropped by name rather than by an
    # "OPENCODE_" prefix on purpose: `OPENCODE_API_KEY` is a provider
    # credential, and a worker needs its keys.
    "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT",
    # Dropped so a redirect can take: `setdefault` cannot override a value the
    # parent already exported, and this one usually is exported. It is broader
    # than the others -- every XDG-respecting tool the child runs sees the
    # workspace copy -- which is the point of an isolated worker.
    "XDG_CONFIG_HOME",
)


#: The host config/home directories a *detached run* keeps (#1082 review).
#:
#: The candidate worker redirects these into its own workspace
#: (:func:`agentdescent.agents.worker_env`), but the detached run is this
#: package: ``integrations._host_root`` reads all four so a worker spec with
#: ``isolate: false`` -- and every ``agentdescent start`` from a plain terminal
#: -- resolves the user's configured home. Dropping them sent such a run to
#: ``~/.claude`` / ``~/.codex`` / ``~/.config``, which for a custom directory is
#: the wrong, often unauthenticated, login. ``XDG_CONFIG_HOME`` is the one
#: OpenCode actually follows, which is why it is here too. The names are listed
#: here, not imported from ``agents``, because this module stays a leaf; the test
#: ``test_the_keep_set_covers_every_variable_host_root_reads`` reads the names
#: out of ``integrations``' own source, so a fifth host root fails it.
DETACHED_KEEP_VARS: Tuple[str, ...] = (
    "CLAUDE_CONFIG_DIR", "CODEX_HOME", "DSH_HOME", "XDG_CONFIG_HOME",
)


def is_session_marker(name: str) -> bool:
    """Whether ``name`` belongs to a host agent's session rather than to the run.

    ``CLAUDECODE`` is a bare name, not a prefix, so a marker matches when the
    variable is the marker without its trailing underscore, or starts with the
    marker itself.
    """
    upper = name.upper()
    return any(upper == marker.rstrip("_") or upper.startswith(marker)
               for marker in SESSION_MARKERS)


def scrub_host_env(environ: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Drop the host session's markers and MCP config from a child environment.

    The candidate's gates run under an allowlist (:func:`runners._child_env`),
    but a detached run is our own process: it needs the API keys and ``PATH``
    that an allowlist would drop. A denylist of the host-session variables keeps
    the credentials while the worker's identity -- and any MCP config that would
    hand the child a second set of tools -- stays with the host (#1082).

    The list is :data:`SESSION_MARKERS`, the same one the candidate worker
    drops, so the two cannot drift apart again. The exception is
    :data:`DETACHED_KEEP_VARS`: those three name the host's *configuration*, not
    its session, and this run resolves a host's real home from them.
    """
    env = dict(os.environ if environ is None else environ)
    return {name: value for name, value in env.items()
            if name.upper() in DETACHED_KEEP_VARS or not is_session_marker(name)}


def _allowed_module(module_name: str, allow: Optional[Sequence[str]]) -> bool:
    if allow is None:
        return True
    if not allow:
        return False
    for prefix in allow:
        prefix = str(prefix).strip()
        if not prefix:
            continue
        if module_name == prefix.rstrip(".") or module_name.startswith(
                prefix if prefix.endswith(".") else prefix + "."):
            return True
    return False


def ensure_write_path(path: Any, *, name: str,
                      allow: Optional[Sequence[str]] = None) -> Optional[str]:
    """Resolve a write path and enforce the operator's allowlist when set."""
    if path is None:
        return None
    resolved = os.path.abspath(os.path.expanduser(require_text(path, name)))
    if allow is not None:
        target = os.path.normcase(os.path.realpath(resolved))
        roots = [os.path.normcase(os.path.realpath(os.path.expanduser(str(root))))
                 for root in allow]
        if not roots or not any(
                target == root or target.startswith(root.rstrip(os.sep) + os.sep)
                for root in roots):
            raise SurfaceError(
                f"{name} {path!r} is outside the operator's write allowlist "
                f"(AGENTDESCENT_SURFACE_WRITE_DIRS)")
    return resolved


def resolve_ref(ref: Any, *, name: str,
                allow: Optional[Sequence[str]] = None) -> Any:
    """Resolve ``module:attribute``; the message names the ref on failure."""
    text = require_text(ref, name)
    if ":" not in text:
        raise SurfaceError(
            f"{name} must be 'module:attribute', got {text!r}")
    module_name, attribute = text.rsplit(":", 1)
    if not _allowed_module(module_name, allow):
        raise SurfaceError(
            f"{name} {text!r} is outside the operator's ref allowlist "
            f"(AGENTDESCENT_SURFACE_ALLOW)")
    try:
        module = importlib.import_module(module_name)
    except Exception as error:  # noqa: BLE001 - the spec's import is user code
        raise SurfaceError(
            f"{name} {text!r} cannot import {module_name!r}: "
            f"{type(error).__name__}: {error}") from None
    try:
        return getattr(module, attribute)
    except AttributeError:
        raise SurfaceError(
            f"{name} {text!r}: module {module_name!r} has no attribute "
            f"{attribute!r}") from None


def resolve_builder(ref: Any, *, name: str,
                    allow: Optional[Sequence[str]] = None) -> Any:
    """Resolve a ref and call it when it is a function/class builder.

    Specs usually point at a factory (``mypkg.wiring:build_pipeline``), but a
    module may also expose a ready object. A function, builtin, method or class
    is called once; a callable instance is returned as-is (it is already the
    object the spec wanted). A failure names the ref instead of leaking a raw
    traceback.
    """
    value = resolve_ref(ref, name=name, allow=allow)
    if (inspect.isfunction(value) or inspect.isbuiltin(value)
            or inspect.ismethod(value) or inspect.isclass(value)):
        try:
            value = value()
        except Exception as error:  # noqa: BLE001 - the builder is user code
            raise SurfaceError(
                f"{name} builder {ref!r} failed: "
                f"{type(error).__name__}: {error}") from None
    return value


def parse_csv(value: Any, *, name: str, cast=str) -> tuple:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        parts = list(value)
    else:
        raise SurfaceError(f"{name} must be a comma-separated string or a list")
    try:
        return tuple(cast(part) for part in parts)
    except (TypeError, ValueError) as error:
        raise SurfaceError(f"{name} has an invalid value: {error}") from None


def parse_floats(value: Any, *, name: str) -> tuple:
    return parse_csv(value, name=name, cast=float)


def parse_ints(value: Any, *, name: str) -> tuple:
    return parse_csv(value, name=name, cast=int)
