Fixed
`agentdescent skills` now treats the store leaf as a regular file: a directory,
device or FIFO named by `--store` is refused with `cannot read skill bank …: not
a regular file` instead of reporting `skills: 0`, and every write refuses a
symlink store before it creates anything, so `--apply` can no longer replace the
link and leave the link and its target disagreeing. A link to a file still
reads. `audit --apply` now prints `applied: false` when no status changed (it
used to echo the flag), which is a visible change to that output line.
