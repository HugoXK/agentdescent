#!/usr/bin/env bash
# Start a long evolution run outside the worker's process group, then hand it
# back (#964). The worker reports `waiting` and ends its turn; a follow-up
# Trigger, a person or a scheduled check reads the run with `status`/`show`.
#
#   dsh-superagent-run.sh --store DIR -- agentdescent --store DIR evolve spec.json --detach
#
# The wrapper's --store is where the report goes; the run's store is the CLI's
# own --store. Give both the same value, or the run lands in the default store
# and the report says found: false.
#
# tmux is preferred because dsh-superagent already depends on it and a session
# is not in the worker's process group, so the kill that ends the worker's
# background job does not reach the run. `setsid` is the fallback: it survives
# that kill, not a reboot -- the run directory, not the process, is what a
# worker hands on.
#
# Exit 0 once the run is detached and DIR/waiting.json is written. It never
# waits for the run: a handoff that blocks is the failure this replaces.
set -euo pipefail

WAIT="${DSH_RUN_HANDOFF_WAIT:-10}"   # seconds to wait for the run's status.json

die() { echo "error: $*" >&2; exit 2; }
usage() { awk 'NR > 1 && /^#/ {sub(/^# ?/, ""); print; next} NR > 1 {exit}' "$0"; }

STORE=""; CMD=()
while [ $# -gt 0 ]; do
  case "$1" in
    --store) [ $# -ge 2 ] || die "--store needs a directory"; STORE="$2"; shift 2 ;;
    --) shift; CMD=("$@"); break ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done
[ -n "$STORE" ] || die "--store is required"
[ ${#CMD[@]} -gt 0 ] || die "nothing to start: give -- <command ...>"
mkdir -p "$STORE"
STORE="$(cd "$STORE" && pwd)"
command -v python3 >/dev/null || die "python3 is required to write the handoff report"

LOG="$STORE/worker.log"
# The store's basename is not unique -- a worker that hands off two runs keeps
# both in a directory called `runs` -- so the session carries a per-launch
# suffix. Two handoffs then never ask tmux for the same name (#1084 review).
SESSION="ad-$(printf '%s' "$(basename "$STORE")" | tr -c 'A-Za-z0-9_.-' '-')-$$-$RANDOM"
# Report text only: this string is what `waiting.json` shows as `command`, and
# nothing ever executes it.
QUOTED="$(printf '%q ' "${CMD[@]}")"
# The log path and the command reach the driver as **arguments**, never spliced
# into a shell string: the old `>> '$LOG'` let an apostrophe in --store close the
# quote, and the rest of the path ran as shell words outside the worker's process
# group with the operator's privileges (#1109). `exec >>"$1"` opens the log,
# `shift` drops it from argv, and the run is exec'd in this process, so it keeps
# the same process group and exit status and nothing re-parses either value.
LAUNCH=(bash -c 'exec >>"$1" 2>&1; shift; exec "$@"' _ "$LOG")

# What the store already holds, taken before the launch: a reused store always
# has earlier runs in it, and reporting the newest of those as this handoff is
# worse than reporting nothing (#1084 review). Only a status.json that this
# launch creates or rewrites may be reported.
SNAP="$STORE/.handoff-$$-$RANDOM.json"
trap 'rm -f "$SNAP"' EXIT
python3 - "$STORE" "$SNAP" <<'PY'
import glob, json, os, sys
store, out = sys.argv[1:3]
snap = {}
paths = [os.path.join(store, "status.json")] + sorted(
    glob.glob(os.path.join(store, "*", "status.json")))
for path in paths:
    if os.path.isfile(path):
        st = os.stat(path)
        snap[path] = [st.st_mtime, st.st_size]
with open(out, "w", encoding="utf-8") as fh:
    json.dump(snap, fh)
PY
if command -v tmux >/dev/null 2>&1; then
  DRIVER=tmux
  tmux new-session -d -s "$SESSION" -c "$PWD" "${LAUNCH[@]}" "${CMD[@]}" \
    || die "tmux refused the session $SESSION"
elif command -v setsid >/dev/null 2>&1; then
  DRIVER=setsid
  setsid "${LAUNCH[@]}" "${CMD[@]}" >/dev/null 2>&1 &
else
  die "neither tmux nor setsid is available; this host cannot hand off a run"
fi

# The run owns its status.json (`<store>/<run_id>/status.json`, or the store
# itself when the caller owns the run directory). Absent is reported as such:
# an invented run id is worse than a gap a Trigger can see.
python3 - "$STORE" "$WAIT" "$DRIVER" "$SESSION" "$LOG" "$QUOTED" "$SNAP" <<'PY'
import glob, json, os, sys, time
store, wait, driver, session, log, command, snap_path = sys.argv[1:8]
before = json.load(open(snap_path, encoding="utf-8"))
deadline, found = time.time() + float(wait), None
while time.time() < deadline:
    paths = [p for p in [os.path.join(store, "status.json")]
             + sorted(glob.glob(os.path.join(store, "*", "status.json")))
             if os.path.isfile(p)]
    fresh = []
    for path in paths:
        try:
            st = os.stat(path)
        except OSError:
            continue
        seen = before.get(path)
        if seen is None or [st.st_mtime, st.st_size] != seen:
            fresh.append(path)
    if fresh:
        found = max(fresh, key=os.path.getmtime)
        break
    time.sleep(0.2)
run_dir = os.path.dirname(found) if found else store
status = json.load(open(found)) if found else {}
report = {"status": "waiting", "found": bool(found),
          "run_id": status.get("run_id", "") if found else "",
          "round": status.get("round", 0), "state": status.get("state", "unknown"),
          "run_dir": run_dir, "driver": driver,
          "session": session if driver == "tmux" else "", "log": log,
          "command": command.strip()}
path = os.path.join(store, "waiting.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2, sort_keys=True)
    fh.write("\n")
print(f"waiting {report['run_id'] or '(no run yet)'} round {report['round']} {run_dir}")
print(f"report {path}")
PY
