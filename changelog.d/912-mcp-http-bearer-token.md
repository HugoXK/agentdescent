Security
`agentdescent mcp --transport streamable-http` can now require an
`Authorization: Bearer` header (`--http-token-env NAME`, with the token read
from the environment and never from the command line). A request without it is
answered 401 before an MCP session is created, so a leaked tunnel URL no longer
reaches `apply` or `start`; `--allow-remote` is refused without a token (#912).
