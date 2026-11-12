Fixed
The last artifact writes outside the run store now report a refused write as
one `error: cannot write <path>: <reason>` line with exit 2 instead of a
traceback: `init --out` over an existing spec (the `.bak-N` copy runs before the
wrapped `open`), and `apply --from <file>` / `apply --from <dir>` when the
destination's parent cannot be created, including the tree branch's per-entry
writes and backups (#994).
