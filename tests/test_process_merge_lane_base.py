"""The merge lane reads its trust inputs from the PR's base commit (#978).

The review-pr skill runs the lane inside the PR clone, so a branch that edits
``.github/agent/review-policy.json`` could list its own author as a reviewer and
one that edits ``.github/agent/risk-rules.json`` could call ``.github/**`` low
risk. Each test builds a clone whose branch does exactly that, copies the lane's
three scripts in (as they are at the PR head), and runs the lane from inside it
with a fake ``gh``. Both files must be read from the PR's base commit with
``git show <base_sha>:<path>``; a clone that cannot serve either gets no lane at
all. Independently of the rules file, a diff touching ``.github/**`` or
``.claude/skills/**`` is T3.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
POLICY = {"version": 1, "reviewers": ["Birfy"], "selfReview": ["Birfy"]}
RULES = json.loads((ROOT / ".github" / "agent" / "risk-rules.json").read_text(encoding="utf-8"))
LANE_SCRIPTS = ("merge_lane.py", "review_gate.py", "risk_gate.py")
PR_AUTHOR = "Mallory"
HEAD = "0123456789abcdef0123456789abcdef01234567"

FAKE_GH = '''#!/usr/bin/env python3
"""Stand-in for `gh api`: the four reads merge_lane/risk_gate make, from one file."""
import json
import os
import sys

data = json.load(open(os.environ["FAKE_GH_DATA"], encoding="utf-8"))
args = " ".join(sys.argv[1:])
if "/files" in args:
    payload = data["files"]
elif "/comments" in args:
    payload = data["comments"]
elif "/reviews" in args:
    payload = data.get("reviews", [])
else:
    payload = data["pull"]
if isinstance(payload, list):
    print("\\n".join(json.dumps(item) for item in payload))
else:
    print(json.dumps(payload))
'''


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ml = _mod("merge_lane")
rg = _mod("review_gate")


def git(root, *args):
    out = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
    return out.stdout.strip()


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(root, message):
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


def clone(tmp_path, policy=POLICY, rules=RULES):
    """A clone at the PR's base: both trust inputs and the lane's scripts committed."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    for key, value in (("user.name", "AgentDescent Dev-3"),
                       ("user.email", "dev-3@agentdescent.invalid"),
                       ("commit.gpgsign", "false")):
        git(root, "config", key, value)
    write(root, ".github/agent/review-policy.json", json.dumps(policy))
    write(root, ".github/agent/risk-rules.json", json.dumps(rules))
    (root / ".github" / "scripts").mkdir(parents=True, exist_ok=True)
    for name in LANE_SCRIPTS:
        shutil.copy(SCRIPTS / name, root / ".github" / "scripts" / name)
    write(root, "docs/guide.md", "# guide\n")
    return root, commit(root, "base")


def report(tip, verdict="PASS"):
    return "\n".join([f"Tip SHA: `{tip}`", "Ran:", "  - pytest -q → pass", "Not run:",
                      "  - Ark real-model run — no model path changed", f"**Verdict: {verdict}**"])


def review(tip, login="Birfy", at="2026-10-19T10:00:00Z"):
    return {"user": {"login": login}, "body": report(tip), "created_at": at}


def changed(name, lines=1):
    return {"filename": name, "additions": lines, "deletions": 0, "changes": lines,
            "patch": "@@ -0,0 +1 @@\n+x"}


def run_lane(tmp_path, clone_root, head, base, comments=(), files=()):
    """Run the lane the way the skill does: from inside the clone, against the PR's head."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    data = bin_dir / "gh.json"
    data.write_text(json.dumps({"pull": {"head": {"sha": head}, "base": {"sha": base},
                                        "user": {"login": PR_AUTHOR}},
                                "comments": list(comments), "reviews": [],
                                "files": list(files)}), encoding="utf-8")
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
               FAKE_GH_DATA=str(data))
    return subprocess.run([sys.executable, str(clone_root / ".github" / "scripts" / "merge_lane.py"),
                           "--repo", "o/r", "--pr", "7", "--tip", head],
                          cwd=str(clone_root), env=env, capture_output=True, text=True)


def test_a_branch_that_allows_its_own_author_still_gets_no_lane(tmp_path):
    root, base = clone(tmp_path)
    own = dict(POLICY, reviewers=["Birfy", PR_AUTHOR], selfReview=["Birfy", PR_AUTHOR])
    write(root, ".github/agent/review-policy.json", json.dumps(own))
    head = commit(root, "let the author pass itself")

    result = run_lane(tmp_path, root, head, base,
                      comments=[review(head, PR_AUTHOR)], files=[changed("docs/guide.md")])
    out = result.stdout + result.stderr
    assert result.returncode != 0, f"the branch's own PASS must not produce a lane:\n{out}"
    assert "no PASS" in out and "auto-merge" not in out, out
    # An uncommitted edit in the clone must not leak in either.
    assert json.loads(git(root, "show", f"{base}:.github/agent/review-policy.json")) == POLICY


def test_a_branch_that_downgrades_the_rules_still_reports_t3_for_dot_github(tmp_path):
    root, base = clone(tmp_path)
    relaxed = {"version": 1, "unknownPathTier": "T0", "generatedPaths": [], "limits": {},
               "tiers": {"T0": {"paths": [".github/**", ".claude/skills/**"]},
                         "T1": {"paths": []}, "T2": {"paths": []},
                         "T3": {"paths": [], "codeExt": "\\.py$", "testPaths": [],
                                "diffPatterns": [], "diffPatternsNotInTests": [], "topics": []}}}
    write(root, ".github/agent/risk-rules.json", json.dumps(relaxed))
    head = commit(root, "call .github low risk")
    files = [changed(".github/workflows/tests.yml")]

    result = run_lane(tmp_path, root, head, base, comments=[review(head)], files=files)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "T3" in out and "awaiting-approval" in out and "auto-merge" not in out, out
    assert ml.tier_for(files, RULES) == "T3"
    assert ml.tier_for(files, relaxed) == "T3", "the .github/** rule must not be editable by the PR"
    assert ml.tier_for([changed(".claude/skills/review-pr/SKILL.md")], relaxed) == "T3"


def test_a_base_that_cannot_serve_a_trust_input_gives_no_lane_at_all(tmp_path):
    root, base = clone(tmp_path)
    result = run_lane(tmp_path, root, HEAD, "f" * 40, comments=[review(HEAD)],
                      files=[changed("docs/guide.md")])
    out = result.stdout + result.stderr
    assert result.returncode != 0 and "no lane" in result.stderr, out
    assert "auto-merge" not in result.stdout and "awaiting-approval" not in result.stdout, out
    try:
        ml.load_trust_inputs(root, "f" * 40)
    except ml.BaseUnreadable as exc:
        assert "review-policy.json" in str(exc)
    else:
        raise AssertionError("a base that cannot serve the policy must fail closed")


def test_the_unmodified_case_keeps_todays_behaviour(tmp_path):
    root, base = clone(tmp_path)
    result = run_lane(tmp_path, root, HEAD, base, comments=[review(HEAD)],
                      files=[changed("docs/guide.md")])
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "T0" in out and f"--match-head-commit {HEAD}" in out, out
    verdict = rg.decide(HEAD, "Birfy", [{"kind": "comment", "login": "Birfy",
                                         "body": report(HEAD), "at": "2026-10-19T10:00:00Z"}],
                        json.loads((root / ".github/agent/review-policy.json").read_text()))
    assert verdict["ok"]
    assert ml.lane(verdict, "T0") == "auto-merge" and ml.lane(verdict, "T1") == "auto-merge"
    assert ml.lane(verdict, "T2") == "awaiting-approval"
    assert ml.lane(rg.decide(HEAD, "Birfy", [], json.loads(
        (root / ".github/agent/review-policy.json").read_text())), "T0") == "wait"
