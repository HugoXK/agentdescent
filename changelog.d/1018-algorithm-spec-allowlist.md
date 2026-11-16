Fixed
The MCP `algorithm_spec` tool now refuses an `out` path outside the operator's
`AGENTDESCENT_SURFACE_WRITE_DIRS` allowlist instead of writing the spec there.
It was the only writing tool that skipped `_check_write`, so a host could name
any path on the server's filesystem; the default allowlist is unchanged (the
server's cwd and `$AGENTDESCENT_HOME`), and an allowed `out` plans as before
(#1018).
