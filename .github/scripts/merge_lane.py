"""The post-PASS merge lane as data: T0/T1 auto-merge, T2/T3 wait for a click.

    verdict = review_gate.decide(head, author, reports, policy)
    tier    = risk_gate.Gate(risk_gate.load_rules()).judge(files)["tier"]
    lane(verdict, tier) -> "auto-merge" | "awaiting-approval" | "wait"

``lane`` reads only its two inputs and never calls GitHub. The review-pr skill
runs ``python3 .github/scripts/merge_lane.py --pr <n> --repo <owner/repo> --tip
<sha>``, which decides with the same two gates and prints the one command for
the tier; the reviewer runs exactly that. T0/T1 enable auto-merge pinned to the
reviewed tip; T2/T3 add ``awaiting-approval``, leave auto-merge unset and stop
for the maintainer. A T3 that comes only from the size cap takes the T2/T3
branch because the tier is ``risk_gate``'s (#961).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_gate  # noqa: E402  (sibling scripts; the skill runs this file by path)
import risk_gate  # noqa: E402

AUTO = "auto-merge"
APPROVAL = "awaiting-approval"
WAIT = "wait"


def lane(verdict: dict, tier: str) -> str:
    """The lane for one PR: data in, data out, no GitHub call and no mutation."""
    if not verdict.get("ok"):
        return WAIT
    return AUTO if tier in ("T0", "T1") else APPROVAL


def command(chosen: str, repo: str, pr: int, tip: str) -> str:
    """The exact gh command the reviewer runs for ``chosen``."""
    if chosen == AUTO:
        return f"gh pr merge {pr} -R {repo} --auto --squash --match-head-commit {tip}"
    if chosen == APPROVAL:
        return f"gh pr edit {pr} -R {repo} --add-label {APPROVAL}"
    return ""


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def _list(path: str) -> list:
    out = _gh("api", "--paginate", "--jq", ".[]", path)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Post-PASS merge lane by risk tier (AGENTS.md).")
    ap.add_argument("--repo", default=os.environ.get("GH_REPO"))
    ap.add_argument("--pr", type=int, default=int(os.environ["PR"]) if os.environ.get("PR") else None)
    ap.add_argument("--tip", required=True, help="the 40-hex head the PASS names")
    ap.add_argument("--policy", default=review_gate.POLICY)
    args = ap.parse_args(argv)
    if not args.repo or not args.pr:
        ap.error("set GH_REPO and PR, or pass --repo owner/name --pr N")
    with open(args.policy, encoding="utf-8") as fh:
        policy = json.load(fh)
    try:
        pull = json.loads(_gh("api", f"repos/{args.repo}/pulls/{args.pr}"))
        head = pull["head"]["sha"]
        if head.lower() != args.tip.lower():
            print(f"merge-lane: head {head[:12]} is not the reviewed tip {args.tip[:12]}; "
                  "re-review it", file=sys.stderr)
            return 2
        author = (pull.get("user") or {}).get("login", "")
        reports = [{"kind": "comment", "login": (c.get("user") or {}).get("login"),
                    "body": c.get("body"), "at": c.get("created_at")}
                   for c in _list(f"repos/{args.repo}/issues/{args.pr}/comments?per_page=100")]
        reports += [{"kind": "review", "login": (v.get("user") or {}).get("login"),
                     "body": v.get("body"), "at": v.get("submitted_at")}
                    for v in _list(f"repos/{args.repo}/pulls/{args.pr}/reviews?per_page=100")
                    if (v.get("body") or "").strip()]
        tier = risk_gate.Gate(risk_gate.load_rules()).judge(
            risk_gate.pr_files(args.repo, args.pr))["tier"]
    except (subprocess.CalledProcessError, ValueError, KeyError, OSError) as exc:
        print(f"merge-lane: cannot read the PR: {exc}", file=sys.stderr)
        return 1
    verdict = review_gate.decide(head, author, reports, policy)
    chosen = lane(verdict, tier)
    print(f"merge-lane: PR #{args.pr} {tier}, "
          + (f"PASS at {head[:12]}" if verdict.get("ok") else f"no PASS at {head[:12]}")
          + f" -> {chosen}")
    if chosen == WAIT:
        print(f"  no action: {verdict.get('reason')}", file=sys.stderr)
        return 1
    print(f"  {command(chosen, args.repo, args.pr, head)}")
    if chosen == APPROVAL:
        print("  then stop: auto_merge stays null, the maintainer merges with a click")
    return 0


if __name__ == "__main__":
    sys.exit(main())
