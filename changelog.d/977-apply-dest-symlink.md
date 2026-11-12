Fixed
`apply` refuses a symlink planted in the destination (`--to`) instead of
following it: the link itself, or any existing component under `--to`, is named
in the error, so a link at `skills/SKILL.md` can no longer redirect the write -
or the `.bak-N` copy taken before it - to a file outside `--to`. Containment is
checked on the leaf as well as its parent, and the destination rule now lives in
`filetree.dest_problem` beside the tree writer's boundary. The directory
backup slots scan `bak-N` with `lexists` too, so a dangling link there is
skipped instead of crashing the backup copy (#977).
