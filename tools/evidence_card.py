"""Evidence cards: the 12-field schema and its offline ``--check`` validator.

``#951`` publishes every empirical claim as a card that answers the same twelve
questions, so a reader can see what a claim leaves unanswered instead of
inferring it. No evidence is the explicit string ``not reviewed``; there is no
blank field and no omitted field. This module is the schema and the check; the
cards are later slices.

    python -m tools.evidence_card --check [CARD ...]

``--check`` validates ``*.json`` cards in the paths given, or ``reports/evidence``
when none is given (absent is ``0 cards``, not an error). Exit 0 valid, 1 refused
with one line per offending field, 2 input error. No network, no clock, and it
writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA_VERSION = 1

#: The twelve questions a card answers, in the order ``#951`` lists them.
FIELDS = ("held_out", "matched_budget", "cross_model", "cost", "disjoint_search",
          "reliability", "code", "evolved_artifact", "who_edits", "feedback",
          "timing", "topology")

#: The only way to say a field has no evidence; anything else non-empty is a value.
NOT_REVIEWED = "not reviewed"

DEFAULT_DIR = Path("reports") / "evidence"


def validate(card, source="card"):
    """Return the refusal lines for one card; empty means it satisfies v1."""
    if not isinstance(card, dict):
        return [f"{source}: a card must be a JSON object"]
    errors = []
    version = card.get("schema_version")
    if version is None:
        errors.append(f"{source}: schema_version: missing (expected {SCHEMA_VERSION})")
    elif isinstance(version, bool) or version != SCHEMA_VERSION:
        errors.append(f"{source}: schema_version: {version!r}, expected {SCHEMA_VERSION}")
    for name in FIELDS:
        if name not in card:
            errors.append(f"{source}: {name}: missing field")
        elif not isinstance(card[name], str):
            errors.append(f"{source}: {name}: not a string (use '{NOT_REVIEWED}')")
        elif not card[name].strip():
            errors.append(f"{source}: {name}: blank (use '{NOT_REVIEWED}')")
    # schema_version is metadata, not evidence: checked above, never one of the twelve.
    errors.extend(f"{source}: {name}: unknown field"
                  for name in card if name != "schema_version" and name not in FIELDS)
    return errors


def collect(paths):
    """Return ``(cards, input_errors)``; only the implicit default directory is optional."""
    implicit = not paths
    cards, problems = [], []
    for raw in [DEFAULT_DIR] if implicit else paths:
        path = Path(raw)
        if path.is_dir():
            cards.extend(sorted(p for p in path.glob("*.json") if p.is_file()))
        elif path.is_file():
            cards.append(path)
        elif not (implicit and path == DEFAULT_DIR):
            problems.append(f"{path}: no such card or directory")
    return cards, problems


def _report(lines):
    for line in lines:
        print(f"error: {line}", file=sys.stderr)


def check(paths):
    """Validate the named cards and return the exit code."""
    cards, problems = collect(paths)
    if problems:
        _report(problems)
        return 2
    errors = []
    for path in cards:
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: not readable JSON ({exc})")
            continue
        errors.extend(validate(card, str(path)))
    if errors:
        _report(errors)
        return 1
    print(f"{len(cards)} card" if len(cards) == 1 else f"{len(cards)} cards")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m tools.evidence_card",
        description="Validate evidence cards against schema v1.",
    )
    parser.add_argument("--check", nargs="*", metavar="PATH",
                        help=f"cards or directories to check (default: {DEFAULT_DIR})")
    args = parser.parse_args(argv)
    if args.check is None:
        parser.print_usage(sys.stderr)
        return 2
    return check(args.check)


if __name__ == "__main__":
    sys.exit(main())
