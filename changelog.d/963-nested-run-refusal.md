Added
A worker session (`AGENTDESCENT_NESTED=1`, set in every host worker the runner
spawns) can no longer start a nested run through the CLI: `agentdescent evolve`
refuses with exit 2 and `reason: nested-run` before it reads the spec or creates
a run, and `doctor` reports `nested_guard` instead of only a boolean. The MCP
`start` stub carries the same reason and sentence, so a host branches on one
contract. Offline, no new sandbox or auth layer (#963).
