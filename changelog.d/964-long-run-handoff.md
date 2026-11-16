Added
`scripts/dsh-superagent-run.sh` hands a long evolution run off a
dsh-superagent worker: it starts the run in a detached `tmux` session
(`setsid` fallback), writes `waiting.json` with the run id, round and run
directory, and returns at once, so a worker turn no longer holds its slot for
the length of the run (#964).
