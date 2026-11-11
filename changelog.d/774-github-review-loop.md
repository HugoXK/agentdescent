Added
`agentdescent github review`: read a PR's reviews, inline comments and check
runs into one packet, extract classified review constraints (test, security,
api, docs, style, behavior), and report merge readiness with blockers. It is
read-only, never approves or merges, and requires an explicit `requires_human_click`
step; `CHANGES_REQUESTED` and its inline comments are blocking, plain notes are
not turned into tasks, resolved ids can be supplied because REST does not
expose thread resolution, and only a reviewer's latest review counts, so a
change request that reviewer later approved no longer blocks.
