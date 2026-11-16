"""What a review *is*, not what its prose happens to say (#933).

`extract_review_constraints` promotes any review body matching `_ACTION` to
blocking, without looking at the review's state. `_ACTION` contains `add`,
`fix`, `update`, `rename`, `required`, `cannot`, ... so ordinary reviewer prose
trips it -- and the two states whose entire meaning is "not a request"
(`APPROVED`, `DISMISSED`) are the ones mined hardest.

The reported damage: a merged PR whose only blocking row was a **dismissed**
PASS, and an open PR whose `Verdict: PASS` report was blocking because one
unrelated sentence contained "cannot". Severity has to come from the state.
"""

from agentdescent.github_surface import extract_review_constraints


def _severity(constraints, text):
    # The extractor collapses whitespace; compare like with like.
    text = " ".join(text.split())
    for row in constraints:
        if row.text == text:
            return row.severity
    raise AssertionError(f"no constraint for {text!r}: "
                         f"{[(r.text, r.severity) for r in constraints]}")


def _review(rid, state, body, login="alice"):
    return {"id": rid, "state": state, "body": body,
            "user": {"login": login}, "submitted_at": "2026-11-12T05:00:00Z"}


def test_an_approval_with_an_action_word_is_a_suggestion():
    body = "Approved - no changes required."
    rows = extract_review_constraints([_review(1, "APPROVED", body)], [])
    assert _severity(rows, body) == "suggestion"


def test_a_dismissed_review_body_is_a_suggestion():
    """A dismissal is the one review whose meaning is "withdrawn".

    It is never stale (`_DECISIVE_REVIEW_STATES`), so the superseded guard never
    covered it and its prose kept blocking after the block was lifted.
    """
    body = "Please rename the flag"
    rows = extract_review_constraints([_review(1, "DISMISSED", body)], [])
    assert _severity(rows, body) == "suggestion"


def test_a_verdict_pass_report_is_never_blocking():
    """Our own review flow writes this on every PR; a report is not a request."""
    body = ("Tip SHA: abc1234\n\nVerdict: PASS at abc1234\n\n"
            "Ran: pytest -q -> 812 passed.\n"
            "I cannot reproduce the failure that was reported.")
    rows = extract_review_constraints([_review(1, "COMMENTED", body)], [])
    assert _severity(rows, body) == "suggestion"


def test_a_plain_commenting_review_still_promotes_a_request():
    """The heuristic is not deleted -- it just stops applying to non-requests."""
    body = "please add a test for the empty input"
    rows = extract_review_constraints([_review(1, "COMMENTED", body)], [])
    assert _severity(rows, body) == "blocking"


def test_an_inline_comment_on_an_approval_is_a_suggestion():
    body = "please add a test here"
    rows = extract_review_constraints(
        [_review(9, "APPROVED", "Looks good")],
        [{"id": 2, "body": body, "path": "a.py",
          "pull_request_review_id": 9}])
    assert _severity(rows, body) == "suggestion"


def test_an_inline_comment_without_a_decisive_parent_still_blocks():
    body = "please add a test here"
    rows = extract_review_constraints(
        [], [{"id": 2, "body": body, "path": "a.py"}])
    assert _severity(rows, body) == "blocking"


def test_a_change_request_and_its_comments_still_block():
    body = "This removes test coverage for the retry path"
    rows = extract_review_constraints(
        [_review(3, "CHANGES_REQUESTED", body)],
        [{"id": 4, "body": "and please cover it", "path": "a.py",
          "pull_request_review_id": 3}])
    assert _severity(rows, body) == "blocking"
    assert _severity(rows, "and please cover it") == "blocking"
