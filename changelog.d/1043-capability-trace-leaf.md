Fixed
`agentdescent capability init --demo` refuses a symlink planted at
`capability-traces.jsonl` or at `--out` before the first byte, instead of
following the link and destroying the file it points at; a link at `--out` no
longer leaves a half-written traces fixture behind (#1043).

The traces fixture is now staged in a temporary file and renamed into place, so
a hardlink at that leaf keeps the bytes it shares with the file outside, a link
planted between the guard and the write is never dereferenced, and a directory
at the leaf is refused with `cannot write <path>: not a file` instead of a raw
`IsADirectoryError`.
