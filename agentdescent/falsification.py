"""Per-lesson provenance records, kept out of the artifact work tree (#966).

``append_provenance`` stores the review evidence for a committed lesson: the
precondition, what changed, the expected effect, which verifier judged it,
which traces and which evidence card back it. That is evidence *about* a
change, not artifact state, so it must never appear in the ledger's commits.

The first version of this writer (#956) put the files in
``<ledger>/provenance/`` -- inside the work tree -- and ``Ledger._commit``
stages the whole tree with ``git add -A`` (``ledger.py:495``). The next commit
therefore swept ``provenance/<id>.json`` and its ``.lock`` into an unrelated
artifact commit. ``register`` commits on both branches, so the files landed on
the ``stable`` commit, and the following ``dev`` checkout deleted them from
the work tree: the evidence was in the history and nowhere on disk.

Records now live in ``<ledger>/.git/provenance/``. ``git add -A`` never stages
anything under ``.git``, so a record cannot enter an artifact commit, and the
directory is removed with the repository instead of outliving it. The ledger
keeps its repository lock and its ``.git/info/exclude`` there for the same
reason (``ledger._LOCK_NAME`` and ``Ledger._write_excludes``).

The writer also refuses an ``artifact_id`` that is not a single file name: the
id is joined into a path, and ``../artifacts/x`` used to reach -- and merge
into -- the artifact payload itself. Ids are internal today (``ledger.py:447``
joins them the same way), so this is not a new trust boundary, but the writer
must not propagate that assumption into its own path join.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Mapping

__all__ = ["append_provenance"]


def _record_name(artifact_id: Any) -> str:
    """``artifact_id`` as one file name, or a refusal -- never a path join."""
    name = str(artifact_id)
    if (not name or name in (".", "..") or ".." in name or "/" in name
            or "\\" in name or os.path.isabs(name) or "\x00" in name):
        raise ValueError(
            f"provenance artifact id must be a single file name, got {name!r}: "
            "it is joined into the record path and must not be able to leave "
            "it")
    return name


def append_provenance(ledger: Any, artifact_id: str,
                      record: Mapping[str, Any]) -> str:
    """Store one record per ``rule_id``, keyed by artifact, under ``.git/``.

    Called after ``Ledger.commit`` returned, on the same thread. It writes
    review evidence and never artifact state, so it cannot bypass the CAS that
    decided the commit; a second write merges into the same file instead of
    replacing it. The lock is the ledger's own mechanism, on a file that is also
    outside the work tree.
    """
    from .ledger import _acquire_file_lock, _release_file_lock

    name = _record_name(artifact_id)
    root = os.path.join(str(getattr(ledger, "repo_path", ".")), ".git",
                        "provenance")
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, f"{name}.json")
    lock_path = path + ".lock"
    handle = _acquire_file_lock(lock_path)
    try:
        data: Dict[str, Any] = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, ValueError):
                data = {}
        data[str(record["rule_id"])] = dict(record)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        _release_file_lock(handle, lock_path)
    return path
