Fixed
The product surfaces (`governed-harness`, `platform`, `capability`,
`meta-campaign`, `ops`, `tenant`, `traces`, `compile-skill`) and the MCP writers
now refuse a symlink planted at the output leaf — one `error: SurfaceError:
cannot write …: '<leaf>' is a symlink` line, exit 2, without touching the link
or its target — instead of silently replacing the operator's link with a
regular file (#1029).
