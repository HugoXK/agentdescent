Fixed
`ExperienceStore.add` refuses a link planted at the `--store` leaf before the
first byte — a symlink, a hardlink and a dangling symlink each appended
wherever the link pointed — and refuses a leaf that is not a regular file,
with the sibling writers' `cannot write <path>: <problem>` shape (#1064).
