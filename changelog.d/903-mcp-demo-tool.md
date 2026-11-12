Added
MCP Path A now has a `demo` tool (`algorithm`, optional `kind`) that returns
the same payload as `agentdescent demo --json`, so a host can run the zero-key
smoke without a provider key. The shared skill tells hosts to try `demo` (or
`agentdescent demo --json`) before doctor → plan → start (#903).
