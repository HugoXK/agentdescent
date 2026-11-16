"""The review gate takes the reviewer's newest report at a tip, verdict or not (#928).

`decide` only ever compared reports that carry a ``Verdict:`` line, so a newer
report at the same tip with no such line - a reversal written in prose, a newly
added requirement, or a follow-up question - was invisible and an older
``Verdict: PASS`` at that tip kept counting. The gate would release a merge on
evidence the reviewer had already moved past.

The rule now: for one tip, the newest report by time across comments and
reviews together decides. It must be a PASS; any other newest report at that
tip voids every earlier PASS there until a new PASS is written. A Verifier
report that names a different tip is still judged against that other tip.

A verdict-less report has no thread identity: the collector reads comment and
review bodies only, with no reply or thread ids, so such a report attaches to
the tip that reviewer most recently named. When that is the head it supersedes
the head's PASS even if the prose is about an earlier tip. That direction is
deliberately conservative - a report the gate cannot place is treated as a
report at the tip it can place it on, never as silence.

The first test is the shape seen live at PR #782: a PASS at
``b0fcd1589d46f14523164f6274d56c2c2300becb`` followed the next day by a
same-tip comment asking for two things before the merge click, with no
``Verdict:`` line.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / ".github" / "agent" / "review-policy.json").read_text())
HEAD = "b0fcd1589d46f14523164f6274d56c2c2300becb"
OLD = "fedcba9876543210fedcba9876543210fedcba98"
WEAK = "no Ran:/Not run:"

# The live follow-up from #782, verbatim in substance: no verdict line, no tip line.
FOLLOW_UP_782 = (
    "Two things I want settled before the merge click: 1. Please run it against one real harness repo, "
    "not just the synthetic tree. 2. The full suite's 20 failed / 10 errors are attributed to no docker "
    "daemon on that host. Can you paste the same run against a host that has one?"
)


def _mod():
    spec = importlib.util.spec_from_file_location("review_gate", ROOT / ".github" / "scripts" / "review_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _mod()


def report(verdict="PASS", tip=HEAD[:12], ran=("pytest -q → pass",), not_run=True):
    lines = [f"Tip SHA: `{tip}`", "Ran:"] + [f"  - {r}" for r in ran]
    if not_run:
        lines += ["Not run:", "  - Ark real-model run — no code path to a model changed"]
    return "\n".join(lines + [f"**Verdict: {verdict}**"])


def c(body, login="Birfy", at="2026-11-10T10:00:00Z", kind="comment"):
    return {"login": login, "body": body, "at": at, "kind": kind}


def test_the_782_follow_up_voids_the_pass_it_follows():
    passed = c(report("PASS", tip=HEAD), at="2026-11-10T02:06:09Z")
    follow_up = c(FOLLOW_UP_782, at="2026-11-11T01:56:00Z")
    r = rg.decide(HEAD, "HugoXK", [passed, follow_up], POLICY)
    assert not r["ok"], "a newer same-tip report with no verdict must void the older PASS"
    assert "no verdict" in r["reason"] and "superseded" in r["reason"]


@pytest.mark.parametrize(
    "newer",
    [
        pytest.param(report("FAIL", tip=HEAD), id="explicit-fail"),
        pytest.param(report("INC", tip=HEAD), id="explicit-inc"),
        pytest.param(
            "I have to take that PASS back - the run I judged is not the one this tree produces.",
            id="prose-withdrawal",
        ),
        pytest.param(
            "Before the merge click: also run the full suite on a host with a docker daemon.",
            id="added-requirement",
        ),
        pytest.param(
            "Did the full suite run anywhere with a docker daemon? I need the answer before a click.",
            id="open-question",
        ),
    ],
)
def test_all_four_superseding_shapes_void_a_verdict_pass(newer):
    passed = c(report("PASS", tip=HEAD), at="2026-11-10T02:06:09Z")
    newer_report = c(newer, at="2026-11-11T01:56:00Z")
    assert not rg.decide(HEAD, "HugoXK", [passed, newer_report], POLICY)["ok"]


def test_a_newer_pass_at_the_same_tip_still_counts():
    early = c(report("PASS", tip=HEAD), at="2026-11-10T02:06:09Z")
    later = c(report("PASS", tip=HEAD), at="2026-11-11T01:56:00Z")
    r = rg.decide(HEAD, "HugoXK", [early, later], POLICY)
    assert r["ok"] and r["by"] == "Birfy" and r["verdict"] == "PASS"


def test_a_pass_written_after_the_follow_up_restores_the_green():
    passed = c(report("PASS", tip=HEAD), at="2026-11-10T02:06:09Z")
    follow_up = c(FOLLOW_UP_782, at="2026-11-11T01:56:00Z")
    second_pass = c(report("PASS", tip=HEAD), at="2026-11-11T03:00:00Z")
    assert not rg.decide(HEAD, "HugoXK", [passed, follow_up], POLICY)["ok"]
    assert rg.decide(HEAD, "HugoXK", [passed, follow_up, second_pass], POLICY)["ok"]


def test_a_follow_up_whose_last_named_tip_is_older_does_not_count_at_the_head():
    old_pass = c(report("PASS", tip=OLD), at="2026-11-10T02:06:09Z")
    follow_up = c(FOLLOW_UP_782, at="2026-11-11T01:56:00Z")
    r = rg.decide(HEAD, "HugoXK", [old_pass, follow_up], POLICY)
    assert not r["ok"]
    assert "not the tip" in r["reason"] and "superseded" not in r["reason"]


def test_prose_about_an_earlier_tip_voids_the_head_pass_it_follows():
    # The conservative direction, pinned: the collector has no thread ids, so a
    # follow-up attaches to the tip this reviewer last named. Here that is the
    # head, and the follow-up voids the head's PASS even though its prose is
    # about OLD. Deliberate, not accidental: silence would release a merge on a
    # reviewer who is still writing at this PR.
    old_pass = c(report("PASS", tip=OLD), at="2026-11-10T02:00:00Z")
    head_pass = c(report("PASS", tip=HEAD), at="2026-11-10T03:00:00Z")
    follow_up = c("A note on the earlier tip: I still think that FAIL was wrong.", at="2026-11-11T01:00:00Z")
    r = rg.decide(HEAD, "HugoXK", [old_pass, head_pass, follow_up], POLICY)
    assert not r["ok"]
    assert "no verdict" in r["reason"] and "superseded" in r["reason"]


def test_an_old_tip_pass_still_fails_on_its_own_tip_after_a_follow_up():
    # The same thread judged at its own tip: the follow-up supersedes there.
    old_pass = c(report("PASS", tip=OLD), at="2026-11-10T02:06:09Z")
    follow_up = c(FOLLOW_UP_782, at="2026-11-11T01:56:00Z")
    r = rg.decide(OLD, "HugoXK", [old_pass, follow_up], POLICY)
    assert not r["ok"] and "no verdict" in r["reason"]


def test_a_review_body_is_ordered_with_comments_by_time():
    passed = c(report("PASS", tip=HEAD), at="2026-11-10T02:06:09Z")
    later_review = c(FOLLOW_UP_782, at="2026-11-11T01:56:00Z", kind="review")
    assert not rg.decide(HEAD, "HugoXK", [passed, later_review], POLICY)["ok"]
    later_pass = c(report("PASS", tip=HEAD), at="2026-11-11T01:56:00Z", kind="review")
    assert rg.decide(HEAD, "HugoXK", [passed, later_pass], POLICY)["ok"]


def test_a_comment_by_someone_who_is_not_a_reviewer_does_not_void_a_pass():
    passed = c(report("PASS", tip=HEAD), at="2026-11-10T02:06:09Z")
    chatter = c("Green at the tip; please re-review.", login="HugoXK", at="2026-11-11T01:56:00Z")
    assert rg.decide(HEAD, "HugoXK", [passed, chatter], POLICY)["ok"]


def test_prose_before_any_named_tip_is_not_a_report():
    r = rg.decide(HEAD, "HugoXK", [c("Looks suspicious, hold the merge.")], POLICY)
    assert not r["ok"] and "no Verifier report names the tip" in r["reason"]


def test_the_winning_pass_keeps_the_evidence_handling():
    weak_pass = c(report("PASS", tip=HEAD, ran=(), not_run=False), at="2026-11-10T02:06:09Z")
    r = rg.decide(HEAD, "HugoXK", [weak_pass], POLICY)
    assert r["ok"] and r["weak"] == WEAK
    follow_up = c(FOLLOW_UP_782, at="2026-11-11T01:56:00Z")
    assert not rg.decide(HEAD, "HugoXK", [weak_pass, follow_up], POLICY)["ok"]
