Fixed
A failed `plan --probe` or `algorithms run --probe` no longer ends with
`next: agentdescent evolve`. The last line (and the JSON `next`) is the
repair action, `--json` sets `ready: false` while leaving `ok` about the
plan itself, and a successful or omitted probe is unchanged (#1093).
