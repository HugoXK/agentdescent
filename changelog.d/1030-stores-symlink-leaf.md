Fixed
The workspace registry, the consolidation archive (`archive`, `mark_exam`) and
the run store's atomic JSON writer refuse a symlink planted at their own file
instead of silently replacing it with a regular file: `cannot write <path>:
'<leaf>' is a symlink`, raised before any temporary exists, with the link and
its target's bytes untouched. A symlinked directory above the file still
works (#1030).
