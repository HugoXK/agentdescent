Fixed
`init` and `algorithms run` refuse a symlink planted at the destination — the
`--out` leaf, the `<stem>.opencode-providers.json` file, and the starter
directories a skill library is seeded into — instead of writing through it, so
the spec can no longer land outside the tree and no `.bak-N` copy holds a file
from outside it (#1008).
