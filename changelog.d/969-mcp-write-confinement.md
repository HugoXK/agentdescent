Fixed
MCP `apply` validates resolved destinations, changed tree entries and backup
paths against the operator's write allowlist before writing. The shared path
guard also resolves directory links, including Windows junctions, so an
allowed path spelling cannot redirect a write outside the configured roots (#969).
