# dsh-super-agent — the zero-code composition

> Status: **reference page, written against `main`; not executed on a live
> dsh-superagent host.** What is verified here is the plugin's rows, the CLI
> commands they name, the command dsh itself prints for a missing profile, and
> the offline pilot the verification script runs. What needs a live host is
> marked *unverified on this page*; `scripts/verify-dsh-superagent.sh` settles it
> on your machine, and skips rather than guesses when it cannot compose (no dsh,
> no profile, or a read-only DSH home — this page's authoring box is the last one).

AgentDescent does not need a new plugin for [dsh-super-agent](https://github.com/deepseek-ai/dsh-superagent-prototype).
The rows it already ships are ordinary Cordis rows, so the same install that
works for the `web` profile composes in the `superagent` profile. This page is
the shortest path from a fresh checkout to one offline pilot run from a
`dsh-superagent-worker`, and the four traps that make it fail silently.

## 1. What composes

`integrations/dsh-agentdescent/cordis.patch.yml` contributes two rows:

- `dsh-agentdescent` — the skill, registered at runtime, so it cannot drift from
  the package;
- `mcp-agentdescent` — a `@deepseek-ai/dsh-mcp-client` row with
  `command: agentdescent`, `args: ["mcp"]`, `transport: stdio`, a 120000 ms
  tool-call timeout, and an explicit env allowlist because dsh scrubs
  `KEY|PASSWORD|SECRET|TOKEN` from the ambient environment
  (`integrations/dsh-agentdescent/cordis.patch.yml:8-26`).

Rows are `insert`ed, not overridden: a bare row would be read as an override of
an id that does not exist and dsh composes without it — the same trap the file's
own header names.

`agentdescent install dsh` is the file-based alternative: it writes
`$DSH_HOME/skills/agentdescent/SKILL.md`, `$DSH_HOME/skills/agentdescent/hooks.json`,
and a marked block in `$DSH_HOME/cordis.patch.yml`
(`agentdescent/integrations/__init__.py:345-355`). Use the plugin or the files,
never both: two `mcp-agentdescent` rows expose the same tools twice.

## 2. Install into the `superagent` profile

The profile is chosen by the same flag the plugin README documents for `web`
(`integrations/dsh-agentdescent/README.md`):

```bash
pip install "agentdescent[mcp]"
dsh plugin --profile superagent add link:/path/to/dsh-agentdescent
```

*Unverified on this page:* that the `superagent` profile behaves exactly as
`web` does. What dsh itself does say: `dsh --profile superagent --dump-config`
fails with `profile "superagent" does not exist; create it with 'dsh plugin
--profile superagent add <package>'`, so the profile is created by the install
rather than before it. If `dsh plugin --profile superagent` reports no plugin
surface, use the file-based install instead — it needs no profile support beyond
the skill directory dsh already reads:

```bash
agentdescent install dsh
```

## 3. Verify the rows, not the intent

```bash
dsh --profile superagent --dump-config | grep -n agentdescent
agentdescent doctor
```

The first command must print both rows: `dsh-agentdescent` and
`mcp-agentdescent`. One row means the other was dropped as a dangling override.
`doctor` reports which agents, keys and optional pieces this machine actually
has; it does not prove the worker preset exposes the tools, which is step 4.

## 4. The worker loop, and the one rule

A worker asks for a Ticket, plans, starts, and then **hands the run back** — it
does not apply:

```text
plan   -> validate the spec and estimate the cost   (writes nothing)
start  -> create the run                            (writes under the store)
status -> progress; a long run survives a turn boundary
show   -> the pilot report and the learned artifact
```

Then attach the pilot report to the Ticket and stop. `--dry-run` or an offline
`text` kind first is the cheap rehearsal; a real model run costs tokens and
should be its own Ticket.

The no-auto-apply rule is not stylistic: a run's artifact is a candidate, and
applying it is a separate, reviewed step (`apply` is the tool that writes into
your tree, under the operator's write allowlist).

## 5. Write dirs and budget for a worker

- Set `AGENTDESCENT_SURFACE_WRITE_DIRS` to the worker's own workspace. The
  default is the server's cwd plus `$AGENTDESCENT_HOME`
  (`agentdescent/surface_common.py:178-190`); an empty value refuses every MCP
  write path, which is the safest setting for a worker that should only plan.
  The CLI `apply` reads the same variable, and inside a worker the server
  default applies there as well even when the variable is unset (#1082).
  `algorithm_spec` obeys this allowlist from the release that carries
  [`#1018`](https://github.com/ThinkFlowLab/agentdescent/issues/1018) (fix in
  [`#1022`](https://github.com/ThinkFlowLab/agentdescent/pull/1022)). On an older
  version it can drop a spec outside its Ticket by naming an `out`: set the
  allowlist empty for a plan-only worker, or do not expose `algorithm_spec`
  at all.
- Keep `--store` inside the run directory, so a Ticket's runs are removable with
  the Ticket.
- `plan` is the budget line: it estimates cost without executing. Read it before
  `start`, and put the number in the Ticket.

## 6. Long runs, Reports and Attention

A run outlives a worker turn: `status` is cheap and safe to poll, and the store
is on disk, so a worker that dies mid-run loses its turn, not the run. Report the
run id and the store path in the Ticket rather than pasting a transcript; the
Report is the attachment, the run is the evidence.

Do not start a nested run from inside a run's turn. A worker that evolves a
harness which itself starts runs multiplies cost with no ceiling — keep one run
per Ticket, and make the second one a follow-up Ticket.

## 7. The check

```bash
bash scripts/verify-dsh-superagent.sh
```

It exits `0` when both rows compose, `doctor` answers, and an offline `text`
pilot writes nothing outside its temp run directory. Without dsh it prints a
skip line and exits `0`; set `DSH_SUPERAGENT_REQUIRED=1` to make a missing host
an error (useful in CI on a machine that is supposed to have it).

## Related

- [`#903`](https://github.com/ThinkFlowLab/agentdescent/issues/903) — hosts could
  not reach the offline demo; the `--kind text` path above is the workaround this
  page relies on.
- [`#918`](https://github.com/ThinkFlowLab/agentdescent/issues/918) — `doctor`
  reported `ok` for a launcher that could not start; step 3 checks the rows, not
  just the exit code.
- [Use it from your agent](plugins.md) — the same composition for the other
  hosts, including the `web` profile this page is derived from.
