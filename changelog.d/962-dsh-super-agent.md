Added
`docs/dsh-super-agent.md` and `scripts/verify-dsh-superagent.sh`: the zero-code
composition of AgentDescent with dsh-super-agent — the two Cordis rows in the
`superagent` profile, the skill-or-MCP fallback, the `plan → start → status →
show` worker loop with no auto-apply, write-dir and budget settings for a
worker, and a gated check that skips cleanly without a live host (#962).
