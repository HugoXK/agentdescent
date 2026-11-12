Fixed
`github review` no longer reports `ready: false` because a reviewer's approval
body or a lifted (dismissed) review contains an action word such as `add`,
`required` or `cannot`: the action-word promotion is now keyed on the review
state and applies to comments only, and a review body that is itself a
`Verdict: PASS` report is never blocking. Those rows are still listed as
suggestions, and `CHANGES_REQUESTED` (with its inline comments) still blocks
(#933).
