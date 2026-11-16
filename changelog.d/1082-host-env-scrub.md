Fixed
A detached run no longer inherits the worker's own session: `runstore.launch`
drops every `SESSION_MARKERS` variable -- `DSH_*`, `CLAUDE*`, `CODEX*`, `MCP_*`,
the OpenCode config carriers and `XDG_CONFIG_HOME` -- before it starts the
grandchild, so the host worker's session identity and MCP server configuration
stay with the host while the credentials and `PATH` the run needs still pass
through (#1082). The list is the one the candidate worker already dropped
(`agentdescent.agents.worker_env`); it used to be a second, shorter copy, and
five of its eleven entries crossed the scrub. The host's config/home
directories (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `DSH_HOME`, `XDG_CONFIG_HOME`)
are kept, because they name configuration rather than session and the run
resolves a host's real home from them (#1082).
