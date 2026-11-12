Fixed
A refused artifact write — `init --out`, `algorithms run --out`, or
`apply --to` for a text file or a tree — now prints one
`error: cannot write <path>: <reason>` line and exits 2, or
`{"ok": false, "error": ...}` under `--json`, instead of raising the raw
`OSError` as a traceback. The run store's `cannot create run store ...`
contract (#907) is unchanged (#990).
