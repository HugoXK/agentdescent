Fixed
The `scripts/dsh-superagent-run.sh` handoff no longer reports an earlier run that
is still going. The launch epoch is taken with the `status.json` snapshot, and a
changed file is only reported when its `started` is numeric and no older than
that epoch, so a handoff into a reused store names its own run — or
`found: false` — instead of the earlier run, whose `run_id` the page's read-back
would then have polled (#1101).
