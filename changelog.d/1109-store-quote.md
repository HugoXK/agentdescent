Security
The handoff wrapper no longer builds its launch command as a shell string: the
log path and the run's command reach `tmux`/`setsid` as arguments, so a `--store`
containing `'`, `;`, `$` or a space is used literally instead of closing the
quote and running the rest of the path as shell words outside the worker's
process group (#1109).
