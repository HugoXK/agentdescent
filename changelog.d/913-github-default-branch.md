Security
`agentdescent github publish` now reads the repository before any write and
refuses a proposal branch that is the proposal base, the configured base or the
API's `default_branch`, so a crafted proposal can no longer force-update the
default branch. An existing proposal branch is only fast-forwarded: a rewritten
history raises one actionable error and writes nothing, and the publisher no
longer sends `force: true`. `--dry-run` still makes no network call (#913).
