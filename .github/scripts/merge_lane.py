"""The post-PASS merge lane as data: T0/T1 auto-merge, T2/T3 wait for a click.

    verdict = review_gate.decide(head, author, reports, policy)
    tier    = tier_for(files, rules)
    lane(verdict, tier) -> "auto-merge" | "awaiting-approval" | "wait"

``lane`` reads only its two inputs and never calls GitHub. The review-pr skill
runs ``python3 .github/scripts/merge_lane.py --pr <n> --repo <owner/repo> --tip
<sha>`` inside the PR clone, so the clone's own files are the branch's: both
trust inputs are read from the PR's **base** commit with ``git show
<base_sha>:<path>``, never from the working tree. A clone that cannot serve
either file gives no lane at all (#978). Independently of the rules file,
``.github/**`` and ``.claude/skills/**`` are T3 whatever the computed tier says.
The lane prints the one command for the tier; the reviewer runs exactly that.
T0/T1 enable auto-merge pinned to the reviewed tip; T2/T3 add
``awaiting-approval``, leave auto-merge unset and stop for the maintainer. A T3
that comes only from the size cap takes the T2/T3 branch because the tier is
``risk_gate``'s (#961).
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
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
POLICY_PATH = ".github/agent/review-policy.json"
RULES_PATH = ".github/agent/risk-rules.json"
FORCED_T3 = (".github/", ".claude/skills/")


class BaseUnreadable(Exception):
    """A trust input the PR's base commit cannot serve: fail closed, no lane."""


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


def _show(repo_root: str, base_sha: str, path: str) -> str:
    """``git show <base_sha>:<path>`` in ``repo_root``; a miss is BaseUnreadable."""
    try:
        out = subprocess.run(["git", "-C", str(repo_root), "show", f"{base_sha}:{path}"],
                             check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc)).strip().splitlines()
        raise BaseUnreadable(f"cannot read {path} from the PR's base {str(base_sha)[:12]}"
                             + (f": {detail[0]}" if detail else "")) from exc
    return out.stdout


def load_trust_inputs(repo_root: str, base_sha: str):
    """``(policy, rules)`` as committed at the PR's base, never the clone's files."""
    loaded = []
    for path in (POLICY_PATH, RULES_PATH):
        try:
            loaded.append(json.loads(_show(repo_root, base_sha, path)))
        except ValueError as exc:
            raise BaseUnreadable(
                f"{path} at the PR's base {str(base_sha)[:12]} is not JSON: {exc}") from exc
    policy, rules = loaded
    if not isinstance(policy, dict) or not isinstance(rules, dict) or "tiers" not in rules:
        raise BaseUnreadable("the PR's base does not carry a review policy and a risk-rules file")
    return policy, rules


def hard_t3(files: list):
    """The first changed path in the two prefixes the lane always calls T3.

    Independent of the rules file: the branch may edit ``risk-rules.json``, so
    these two are a rule in the lane itself and not a lookup in it (#978).
    """
    for f in files:
        for name in (f.get("filename"), f.get("previous_filename")):
            if isinstance(name, str) and name.startswith(FORCED_T3):
                return name
    return None


def tier_for(files: list, rules: dict) -> str:
    """risk_gate's tier for the PR's diff, raised to T3 by the two forced prefixes."""
    if hard_t3(files):
        return "T3"
    return risk_gate.Gate(rules).judge(files)["tier"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Post-PASS merge lane by risk tier (AGENTS.md).")
    ap.add_argument("--repo", default=os.environ.get("GH_REPO"))
    ap.add_argument("--pr", type=int, default=int(os.environ["PR"]) if os.environ.get("PR") else None)
    ap.add_argument("--tip", required=True, help="the 40-hex head the PASS names")
    args = ap.parse_args(argv)
    if not args.repo or not args.pr:
        ap.error("set GH_REPO and PR, or pass --repo owner/name --pr N")
    try:
        pull = json.loads(_gh("api", f"repos/{args.repo}/pulls/{args.pr}"))
        head = pull["head"]["sha"]
        base = pull["base"]["sha"]
        author = (pull.get("user") or {}).get("login", "")
        reports = [{"kind": "comment", "login": (c.get("user") or {}).get("login"),
                    "body": c.get("body"), "at": c.get("created_at")}
                   for c in _list(f"repos/{args.repo}/issues/{args.pr}/comments?per_page=100")]
        reports += [{"kind": "review", "login": (v.get("user") or {}).get("login"),
                     "body": v.get("body"), "at": v.get("submitted_at")}
                    for v in _list(f"repos/{args.repo}/pulls/{args.pr}/reviews?per_page=100")
                    if (v.get("body") or "").strip()]
        files = risk_gate.pr_files(args.repo, args.pr)
    except (subprocess.CalledProcessError, ValueError, KeyError, OSError) as exc:
        print(f"merge-lane: cannot read the PR: {exc}", file=sys.stderr)
        return 1
    if head.lower() != args.tip.lower():
        print(f"merge-lane: head {head[:12]} is not the reviewed tip {args.tip[:12]}; "
              "re-review it", file=sys.stderr)
        return 2
    try:
        policy, rules = load_trust_inputs(ROOT, base)
        tier = tier_for(files, rules)
    except BaseUnreadable as exc:
        print(f"merge-lane: no lane: {exc}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError) as exc:
        print(f"merge-lane: no lane: the PR's base rules are unusable: {exc}", file=sys.stderr)
        return 1
    verdict = review_gate.decide(head, author, reports, policy)
    chosen = lane(verdict, tier)
    forced = hard_t3(files)
    print(f"merge-lane: PR #{args.pr} {tier}, "
          + (f"PASS at {head[:12]}" if verdict.get("ok") else f"no PASS at {head[:12]}")
          + f" -> {chosen}" + (f" (T3 forced by {forced})" if forced else ""))
    if chosen == WAIT:
        print(f"  no action: {verdict.get('reason')}", file=sys.stderr)
        return 1
    print(f"  {command(chosen, args.repo, args.pr, head)}")
    if chosen == APPROVAL:
        print("  then stop: auto_merge stays null, the maintainer merges with a click")
    return 0


if __name__ == "__main__":
    sys.exit(main())
