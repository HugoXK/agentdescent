Fixed
`agentdescent serve --host <non-loopback>` now refuses to start, with one
`error:`-style line and exit 2, unless the operator passes `--allow-remote`: the
run panel has no authentication and lists every run in the store, which a single
`--host 0.0.0.0` used to publish to the network. Loopback hosts are unchanged,
and the opt-in prints the same no-authentication warning `agentdescent mcp`
does (#911).
