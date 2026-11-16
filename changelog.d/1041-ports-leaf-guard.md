Fixed
`FileArtifactStore` no longer writes through a link planted at a leaf it
writes: `promote` refuses `<to>` before it reads or removes through it, and
`_commit` refuses `<name>.json` before staging, both as `ValueError: cannot
write <path>: '<leaf>' is a symlink`. The sidecar is now staged and renamed
over that leaf, so a hardlink at `<name>.json` is replaced instead of
truncating the inode it shares with bytes outside `root`. The link and those
bytes are untouched, and a symlinked directory above the store still works
(#1041).
