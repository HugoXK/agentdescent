#!/usr/bin/env bash
# Verify the dsh-super-agent composition (#962), or skip cleanly without dsh.
#
# What it checks:
#   1. the superagent profile composes BOTH AgentDescent rows
#      (`dsh-agentdescent` and `mcp-agentdescent`), not just the skill;
#   2. `agentdescent doctor` answers on this machine;
#   3. an offline `text` pilot writes its fixtures under --dir and its runs under
#      --store, and leaves the caller's cwd clean (the no-stray-write check the
#      doc's step 7 promises).
#
# It never runs a real model: the pilot is the offline demo.
set -euo pipefail

PROFILE="${DSH_SUPERAGENT_PROFILE:-superagent}"

skip() {
  echo "skip: $*" >&2
  if [ "${DSH_SUPERAGENT_REQUIRED:-0}" = "1" ]; then
    echo "fail: DSH_SUPERAGENT_REQUIRED=1 so a missing host is an error" >&2
    exit 1
  fi
  exit 0
}

command -v dsh >/dev/null 2>&1 || skip "dsh not on PATH"
command -v agentdescent >/dev/null 2>&1 || skip "agentdescent not on PATH"

config="$(dsh --profile "$PROFILE" --dump-config 2>&1)" || {
  # A profile that was never created is "not set up yet", not a failure of the
  # composition: dsh names the command that creates it.
  if grep -q "does not exist" <<<"$config"; then
    skip "the $PROFILE profile does not exist yet; create it with" \
         "'dsh plugin --profile $PROFILE add <package>'"
  fi
  # A read-only DSH home (a sandbox, a container without a writable ~/.dsh)
  # cannot compose at all: that is the environment, not the composition.
  if grep -qE "EROFS|read-only file system" <<<"$config"; then
    skip "the dsh home is read-only here, so --dump-config cannot compose"
  fi
  echo "fail: dsh --profile $PROFILE --dump-config exited non-zero" >&2
  printf '%s\n' "$config" >&2
  exit 1
}

for row in dsh-agentdescent mcp-agentdescent; do
  if ! grep -q "$row" <<<"$config"; then
    echo "fail: the $PROFILE profile does not compose the $row row" >&2
    echo "      install the plugin for this profile, or run 'agentdescent install dsh'" >&2
    exit 1
  fi
done

agentdescent doctor >/dev/null || {
  echo "fail: agentdescent doctor exited non-zero" >&2
  exit 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

(
  # A subshell: its `exit 1` becomes the script's exit under `set -e`, and the
  # EXIT trap still removes $work when it does.
  cd "$work"
  # An isolated HOME, so the pilot cannot touch the real ~/.agentdescent.
  export HOME="$work/home"
  export AGENTDESCENT_HOME="$work/home/.agentdescent"
  mkdir -p "$HOME"

  agentdescent --store "$work/runs" demo --kind text --dir "$work/demo" >/dev/null

  test -f "$work/demo/spec.json" || {
    echo "fail: the pilot did not write spec.json under --dir" >&2
    exit 1
  }
  test -d "$work/runs" || {
    echo "fail: the pilot did not write its store under --store" >&2
    exit 1
  }
  # The caller's cwd must stay clean: the writer's only outputs are the two
  # directories above.
  stray="$(find "$work" -maxdepth 1 -mindepth 1 \
    ! -name demo ! -name runs ! -name home -print)"
  if [ -n "$stray" ]; then
    echo "fail: the pilot wrote outside --dir/--store:" >&2
    printf '%s\n' "$stray" >&2
    exit 1
  fi
)

echo "ok: $PROFILE composes both rows, doctor answers, and the offline pilot stayed in its directories"
