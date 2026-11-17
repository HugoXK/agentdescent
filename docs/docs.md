---
description: What AgentDescent is, what it is good at, how to use it, and the self-evolution angles it supports.
---

# Documentation

AgentDescent is a parallel, asynchronous engine for self-evolving LLM agents.
You give it an artifact — a prompt, a skill, a directory, a program or a
harness — a way to try tasks, and a reward. It runs candidates in parallel,
merges their edits, accepts only what the held-out evidence supports, and writes
every accepted change to a git-backed ledger.

**Diffs are the gradients; the aggregator is the optimizer.**

Choose the route that matches what you want to do. Each guide links to the
deeper reference when you need it.

<div class="ad-doc-paths">
  <a href="../install/"><span>01 / START</span><strong>Use it in your agent</strong><small>Install AgentDescent, connect Claude Code, Codex, OpenCode or DeepSeek Harness, and review your first change.</small><b>Open Quickstart ↗</b></a>
  <a href="/#demo"><span>02 / TRY</span><strong>See the interaction</strong><small>Walk through a sample agent conversation in the interactive demo on the homepage.</small><b>Try the demo ↗</b></a>
  <a href="../main-path/"><span>03 / MAP</span><strong>Read the supported path</strong><small>Three paths, the advanced layers, and the canonical module for each concept.</small><b>Open the main path ↗</b></a>
  <a href="../self-evolution-examples/"><span>04 / STUDY</span><strong>Browse 23 algorithm ports</strong><small>See how published methods fit different artifact types and algorithm choices.</small><b>Browse methods ↗</b></a>
</div>

## What it is good at

| strength | in practice | go deeper |
|---|---|---|
| **Parallel and async search** | N workers propose diffs against ledger snapshots; the merger consumes evidence without waiting for a round barrier. | [Async](async.md) · [Parallelism](parallelism.md) |
| **Diff-native merge** | Complementary edits union; contradicting edits are resolved or synthesized; a one-key artifact uses reflective merge. | [Aggregator](aggregator.md) · [Fusion policies](fusion-policies.md) |
| **Evidence-bound acceptance** | A held-out gate, bootstrap/CI, canary, run health and cost decide what commits; missing evidence defers instead of inventing confidence. | [Trust evidence](trust-evidence.md) · [Trusted promotion](trusted-promotion.md) |
| **Any artifact** | An instruction, a rule set, a directory, a program, a harness or your own state through the three-method `Strategy` contract. | [Strategies](strategies.md) · [Directory evolution](directory-evolution.md) |
| **23 algorithm ports** | ACE, GEPA, DGM, OpenEvolve, Reflexion, Voyager and others run as plug-ins on the same engine, so scheduling is a controlled variable. | [All ports](self-evolution-examples.md) |
| **Host integration** | Claude Code, Codex, OpenCode, DeepSeek Harness and any MCP client; local-first and model-agnostic. | [Plugins](plugins.md) · [Ask DeepWiki](deepwiki.md) |
| **Governed change** | Blast radius, invariants, approval and a signed release path for harness or code changes. | [Governance](governance.md) · [Release](release.md) |

!!! note "What it is not"

    A research reference implementation, not a hosted product or a benchmark
    leaderboard. The engine and the evidence layer are the product; a host agent
    or a platform owns the UI. Missing evidence defers, and an unchanged artifact
    is not repriced as a gain. Read [the main path](main-path.md) for the
    supported surface and [the results page](results.md) for the caveats behind
    every number.

## How to use it

1. **Install.** `pip install "agentdescent[mcp]>=0.10.0"`, or run the one-command
   installer. `agentdescent doctor` shows which hosts and keys this machine has.
   [Install and first run](install.md) · [The plugin in three commands](plugin-quickstart.md)
2. **See the loop once, offline.** `agentdescent demo` runs a complete evolution
   with no API key and no files changed:

    ```bash
    $ agentdescent demo
    held-out reward: 0.000 -> 1.000  outcomes: {'committed': 1}
    what it learned: rules.md -> 'COLUMN: amount'
    ```

   The [interactive demo](index.md#demo) walks through the same flow inside a
   host agent.
3. **Point it at your artifact.** From the CLI: `init → plan → evolve → show →
   apply`. Inside an agent: `doctor → plan → start → status → show → apply`.
   [Prompt or skill](quickstart-skill.md) · [Directory](quickstart-directory.md) ·
   [Agent code](quickstart-agent-code.md)
4. **Or call it from Python.** `evolve(tasks, reward, agent=..., strategy=...)`.
   Unspecified policy slots use their defaults.
   [The `evolve()` method](evolution.md) · [Strategies](strategies.md)
5. **Read the evidence.** The report carries the decision, the evidence, the
   cost and the next action. [Measured results](results.md) ·
   [Trust evidence](trust-evidence.md) · [DeepWiki](deepwiki.md) for questions
   about the code.

## Self-evolution angles

AgentDescent separates the loop into decisions you can replace. Choose the angle;
keep the rest of the engine.

| angle | the question | built-in levers | start with |
|---|---|---|---|
| **Artifact** | What changes? | instruction, keyed rules, append-only lessons, file tree, custom `Strategy` | [Strategies](strategies.md) |
| **Proposal** | Who writes the next candidate? | reflection, population, genetic search, self-play, curator, code patch | [Proposal policies](proposal-policies.md) |
| **Sampling** | Which tasks get a rollout? | round-robin, difficulty-weighted, failure-stratified | [Task sampling](sampling.md) |
| **Selection** | Which candidates get evaluated? | single head, population, archive, quality–diversity | [Candidate selection](selection.md) |
| **Merge** | How do concurrent edits combine? | keyed union, conflict resolution, reflective merge, tournament, custom aggregator | [Fusion policies](fusion-policies.md) · [Aggregator](aggregator.md) |
| **Acceptance** | What evidence earns a commit? | Beta posterior, bootstrap/CI, canary, Goodhart, metamorphic, verifier, calibration | [Acceptance policies](acceptance-policies.md) · [Trust evidence](trust-evidence.md) |
| **Promotion and staleness** | When is a version stable, and how do old snapshots age? | K survival rounds, bounded staleness, forced refresh | [Promotion policies](promotion-policies.md) · [Staleness](staleness.md) |
| **Execution** | How does the search run? | serial, synchronous, barrier-free async, task/section/cluster parallelism, budgets | [Async](async.md) · [Parallelism](parallelism.md) · [Budget](budget.md) |
| **Durability** | What survives and can be replayed? | git ledger, lineage, manifest, decision log, trajectory store | [Ledger](ledger.md) · [Manifest](manifest.md) · [Decision log](decisions.md) |
| **Governance and accumulation** | What may a change touch, and what carries across runs? | blast radius, invariants, approval, release; experience, consolidation, meta-evolution | [Governance](governance.md) · [Experience](experience-cli.md) · [Meta-evolution](meta-evolution.md) |

The 8 `Policies` slots, the `Strategy` contract and `aggregator_factory` are the
seams. [Choosing policies](policies.md) · [Using the slots](policy-guide.md) ·
[The main path](main-path.md).

## The three supported paths

| path | you have | the product surface |
|---|---|---|
| **A — evolve one artifact** | tasks, a reward, an actor | `agentdescent plan/evolve/status/show/apply` |
| **B — governed release** | paired held-out scores | `agentdescent release` + `release verify` |
| **C — continuous platform** | a run database and callbacks | `agentdescent platform` + `platform status` |

Read [the main path](main-path.md) first if you are deciding where a new
capability belongs; it is the design contract, not another module list.

## Product surfaces

| surface | verbs | guide |
|---|---|---|
| release | `release`, `release verify` | [Release a candidate](release.md) |
| traces | `traces digest/show` | [Trajectory evidence](traces.md) |
| governed harness | `governed-harness plan/run/approvals/approve/reject` | [Governed harness](governed-harness.md) |
| tenant | `tenant plan/run/report` | [Tenant cycle](tenant.md) |
| operations | `ops plan/publish/history` | [Operations console](ops.md) |
| platform | `platform init/plan/run/status` | [The RSI platform cycle](platform.md) |
| capability growth | `capability init/plan/run` | [Capability loop](capability-loop.md) |

These are product surfaces over the same `evolve()` engine, not separate
algorithms. Each returns `schema_version: 1` and fails closed under `--json`.

## New in 0.10.0

The 0.10.0 line adds cost, scheduling, skill/harness tooling and host surfaces
without changing the core loop:

| area | what it adds | page |
|---|---|---|
| **Cost** | price each accepted diff and compare quality per cost, not only quality. | [Cost per accepted diff](cost.md) |
| **Scheduling** | an expand-vs-evaluate HGM scheduler for where the next rollout goes. | [HGM scheduling](hgm.md) |
| **Predictions** | predict whether an edit is worth paying for before the run. | [Edit predictions](predictions.md) |
| **Skills** | lifecycle and drift audit for the skill bank; compile a skill into a tested function. | [Skill bank](skill-bank.md) · [Skill compilation](skill-compilation.md) |
| **Harness** | a component manifest and edit contract for harness-level changes. | [Harness manifest](harness-manifest.md) |
| **Hosts** | the zero-code DSH super-agent composition and the MCP/CLI Path A surface. | [DSH super-agent](dsh-super-agent.md) · [MCP / CLI Path A](mcp-path-a.md) |
| **Algorithms** | choose a port by artifact and objective, not by name. | [Algorithm decision tree](algorithm-decision-tree.md) |

## Go deeper

**Understand the model.**
[Core concepts](concepts.md) · [Architecture](architecture.md) ·
[Data model](data-model.md) · [Governance](governance.md) ·
[Capability map](capabilities.md) · [Main path](main-path.md).

**Build an evolution loop.**
[The `evolve()` method](evolution.md) · [Strategies](strategies.md) ·
[Policies](policies.md) · [Policy guide](policy-guide.md) ·
[Aggregators](aggregator-factory.md) · [Directory evolution](directory-evolution.md).

**Run and operate it.**
[Parallelism](parallelism.md) · [Async](async.md) · [Execution](execution.md) ·
[Sandboxes](sandboxes.md) · [Budget](budget.md) · [Loop kernel](loop-kernel.md) ·
[Runtime](runtime.md) · [Controller](controller.md) · [Diagnose](diagnose.md) ·
[Trajectory evidence](traces.md) · [Metrics](metrics.md) · [Module audit](module-audit.md).

**Trust, release and govern.**
[Verifier](verifier.md) · [Sparse audit](audit.md) ·
[Statistical evidence](stats-eval.md) · [Trusted promotion](trusted-promotion.md) ·
[Trusted evidence](trust-evidence.md) · [Release](release.md) ·
[Approval](approval.md) · [Safety](safety.md) · [Risk policy](risk-policy.md) ·
[Decision log](decisions.md) · [Manifest](manifest.md).

**Study the methods and measurements.**
[23 self-evolution ports](self-evolution-examples.md) · [Results](results.md) ·
[Efficiency](efficiency.md) · [Runtime matrix](matrix-overview.md) ·
[Harness composition](harness-composition.md) · [Consolidation](consolidation.md) ·
[Self-improvement](self-improve.md) · [Longitudinal RSI](rsi.md).

**Reference and host integration.**
[API reference](api.md) · [Agents](agents.md) · [Plugins](plugins.md) ·
[Plugin quickstart](plugin-quickstart.md) · [Set it up and test it](testing-guide.md) ·
[Usage](usage.md).

**Questions about the code?**
[Ask DeepWiki](deepwiki.md) indexes the repository and answers with links to the
source. The page also shows how to connect its MCP server to Claude Code, Codex,
OpenCode or DeepSeek Harness and ask from your agent.
