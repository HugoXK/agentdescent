"""The post-PASS merge lane by tier (#961).

The review skill applied AGENTS.md's T0/T1 auto-merge step to every PR, so a
T2/T3 PR was merged by an agent and never carried `awaiting-approval`. `lane()`
takes the verdict review_gate.decide() returns plus the tier risk_gate.Gate
computes from the diff (never the PR text), and returns the lane as data: the
T0/T1 auto-merge lane is unchanged, T2/T3 stop for the maintainer, and no
compliant PASS at the tip means no action.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
SKILL = ROOT / ".claude" / "skills" / "review-pr" / "SKILL.md"
RULES = ROOT / ".github" / "agent" / "risk-rules.json"
POLICY = json.loads((ROOT / ".github" / "agent" / "review-policy.json").read_text())
HEAD = "0123456789abcdef0123456789abcdef01234567"


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


assert (SCRIPTS / "merge_lane.py").exists(), (
    "merge_lane.py is missing: the post-PASS step has no tier branch (#961)")
ml = _mod("merge_lane")
rg = _mod("review_gate")
GATE = _mod("risk_gate").Gate(json.loads(RULES.read_text(encoding="utf-8")))


def report(verdict="PASS", tip=HEAD[:12], ran=("pytest -q → pass",), not_run=True):
    lines = [f"Tip SHA: `{tip}`", "Ran:"] + [f"  - {r}" for r in ran]
    if not_run:
        lines += ["Not run:", "  - Ark real-model run — no model path changed"]
    return "\n".join(lines + [f"**Verdict: {verdict}**"])


def c(body, login="Birfy", at="2026-10-19T10:00:00Z", kind="comment"):
    return {"login": login, "body": body, "at": at, "kind": kind}


def passed():
    verdict = rg.decide(HEAD, "Birfy", [c(report())], POLICY)
    assert verdict["ok"]
    return verdict


def f(name, add=1):
    return {"filename": name, "additions": add, "deletions": 0, "changes": add,
            "patch": "@@ -0,0 +1 @@\n+x"}


def test_t2_and_t3_with_a_pass_wait_for_the_maintainers_click():
    for tier in ("T2", "T3"):
        assert ml.lane(passed(), tier) == "awaiting-approval", tier


def test_a_t2_that_escalates_on_the_size_cap_takes_the_t3_lane():
    # T2 paths, 13 files: over T2's 12-file cap, so risk_gate itself says T3.
    result = GATE.judge([f(f"agentdescent/part{i}.py") for i in range(13)])
    assert result["tier"] == "T3"
    assert ml.lane(passed(), result["tier"]) == "awaiting-approval"


def test_t0_and_t1_with_a_pass_still_auto_merge():
    for tier in ("T0", "T1"):
        assert ml.lane(passed(), tier) == "auto-merge", tier


def test_a_stale_pass_means_wait():
    stale = rg.decide(HEAD, "Birfy", [c(report(tip="fedcba9876"))], POLICY)
    assert not stale["ok"] and "not the tip" in stale["reason"]
    assert ml.lane(stale, "T1") == "wait"


def test_a_weak_pass_still_counts_as_a_pass():
    weak = rg.decide(HEAD, "Birfy", [c(report(ran=(), not_run=False))], POLICY)
    assert weak["ok"] and weak["weak"]
    assert ml.lane(weak, "T1") == "auto-merge"


def test_the_commands_are_the_pinned_merge_and_the_label_only():
    assert ml.command("auto-merge", "o/r", 12, HEAD) == (
        f"gh pr merge 12 -R o/r --auto --squash --match-head-commit {HEAD}")
    label = ml.command("awaiting-approval", "o/r", 12, HEAD)
    assert label == "gh pr edit 12 -R o/r --add-label awaiting-approval"
    assert "merge" not in label
    assert ml.command("wait", "o/r", 12, HEAD) == ""


def test_the_skill_quotes_the_lane_command():
    text = SKILL.read_text(encoding="utf-8")
    assert "merge_lane.py" in text, "the skill must run the tiered lane, not one merge command for all PRs"
    assert "awaiting-approval" in text and "wait" in text
