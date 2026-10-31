# Capability map (v0.8.0)

AgentDescent is a parallel, asynchronous framework for evolving prompts, skills,
programs, workflows, harnesses and custom artifacts. It is not one algorithm: it
is a composition surface for **what evolves**, **who proposes**, **what counts
as better**, **what may merge**, and **what is remembered**.

This page is the map. Each section names the modules you can use today and the
seam they own.

## The five primitives

| Primitive | Modules | What it means |
|---|---|---|
| Artifact | `Evolvable`, `Strategy`, `EvolvingArtifact` | The thing being improved: a slot, a skill library, a directory, a harness or a custom state. |
| Diff | `Diff`, `VersionVector` | One candidate change, with rationale and evidence. |
| Evidence | `EvidenceCard`, `Trajectory`, `RunManifest` | Tasks, scores, cost and provenance behind a candidate. |
| Gate | `Policies`, `verifier`, `trust_evidence`, `promotion` | Accept / defer / reject / rollback, fail-closed. |
| Ledger | `Ledger`, `ConsolidationStore`, `DecisionLog` | Versioned artifact, cross-run archive and the decision trace. |

## The evolution loop

- `evolution.evolve()`: one entry point for tasks, reward, actor and strategy.
- `async_evolve` / `async_runtime`: workers produce without a round barrier;
  the merger consumes evidence with staleness and backpressure.
- `parallel`: `DataParallel`, `TensorParallel`, `PipelineParallel`,
  `ClusterParallel`.
- `scheduler`, `budget`, `checkpoint`, `runstore`: duration-aware dispatch,
  graceful degradation, resume and run state.
- `Policies`: eight swappable decisions (task sampler, selection, proposal,
  conflict, fusion, acceptance, promotion, staleness).
- `aggregator_factory`: replace the whole merge path when an algorithm owns its
  population or optimizer.
- `governance`, `staleness`, `treestrategy`, `runters`: frozen paths, stale-diff
  handling, directory state and real-agent rollouts.

## Evaluating and verifying

- `verifier`: rule / learned / oracle, with a budget.
- `verifier_ensemble`: cost-aware cascade, weighted, majority or unanimous;
  incomplete panels fail closed.
- `audit`: cheap verifier against sparse oracle truth (PPI, calibration, drift,
  coverage).
- `jev`, `verifier_curriculum`: distilled verifier and co-evolved curriculum.
- `metamorphic`, `goodhart`: transformed-input relations and proxy-vs-oracle
  reward hacking detection.
- `self_model`, `process_reward`: calibrated confidence/abstention and
  step-level process rewards.
- `planning`, `search_fabric`, `budgeted_search`: UCT/MCTS, PRM/verifier value,
  PRM reranking and marginal-gain stopping.
- `stats_eval`, `conformal`, `sequential`, `evalops`: paired bootstrap,
  split-conformal bounds, anytime-valid e-processes and continuous evaluation.

## Trusted promotion

- `trust_evidence.build_trust_evidence()` turns one paired run into eval +
  bootstrap, canary, conformal, sequential, Goodhart, metamorphic, verifier and
  calibration reports.
- `promotion.promote()` returns `promote / defer / reject / rollback`:
  missing evidence defers, a failed gate rejects, a canary regression rolls back,
  and only a green bundle promotes. Evidence is bound to the artifact id/hash.
- `promotion_ledger` (recently proposed): an accepted promotion becomes a signed
  `ArtifactManifest` and a lineage node carrying evidence and decision hashes.
- `policy_release`, `proofs`, `safe_selfmod`, `capability_guard`, `risk_policy`,
  `approval`, `leakage`: policy-as-code, signed manifests, invariant
  certificates, capability gates, risk actions, human approval and leakage
  detection.

## Running and operating

- `rsi_control`: the accept/reject/defer/rollback/stop policy seam.
- `controller`, `runtime`, `campaign`, `tournament`: bounded sessions,
  `run_guarded`, multi-session campaigns and algorithm tournaments.
- `durable_runs`: SQLite event log, leases, idempotency, retries, resume.
- `workspaces`: tenant/workspace RBAC, quota reservations, scoped audit.
- `rsi_metrics`, `rsi_telemetry`: Prometheus samples and OTel-shaped spans.
- `ops_console`: the read model for runs, approvals, QD, lineage and cost.
- `ops_fabric` (recently proposed): write one `LoopReport` into console,
  lineage, telemetry and a QD snapshot.
- `platform.RSIPlatform` (landed): one cycle of compute → loop → promote →
  foundry → experience, with `complete=False` when a configured layer produces
  no decision.

## Tasks, capabilities and archives

- `data_flywheel`: traces → filtered, redacted, deduplicated dataset candidates.
- `task_foundry`: failure seeds → validated, deduplicated, contamination-checked
  train/holdout tasks.
- `task_pipeline` (landed): the hand-off between those two, respecting the
  foundry's own verdict.
- `tool_synthesis`: generate, validate and select tools; the generator sees
  earlier rejection reasons.
- `capability_foundry`: validation → review → capability gate → proof → holdout
  gain → artifact registration.
- `capability_scout` (recently proposed): failed tasks → tool synthesis →
  capability admission.
- `deliberation`, `society_runtime`, `agent_society`: weighted judge panels,
  blackboard runtimes and multi-agent topology evolution.
- `quality_diversity`, `artifact_graph`, `semantic_dedup`,
  `capability_archive`: MAP-Elites archives, retrieval graphs, near-duplicate
  detection and a capability library that keeps them in sync.
- `openended`, `curious_replay`, `trajectory_curriculum`, `meta_curriculum`:
  task/solver co-evolution, replay-driven and meta-generated curricula.

## Experience and continual learning

- `experience`: append-only cross-run records, nearest-neighbour recall,
  warm-start replay and an anchor forgetting guard with rollback.
- `continual_meta`: online softmax policy with replay, validation and rollback.
- `consolidation`: cross-run artifact archive with a mini-eval seed gate.
- `counterfactual` / `credit`: replay interventions, leave-one-out and Shapley
  step attribution.
- `counterfactual_experience` (recently proposed): step credit → experience
  rewards.
- `preference` / `preference_replay` (recently proposed): pairwise preference
  reward model and preference-ranked replay.
- `self_improve`, `recursive`, `joint_meta`, `meta_audit`, `meta_exam`,
  `meta_population`, `verified_seed`: recursive/joint/meta self-improvement with
  examined and verified seeds.

## Algorithm ports

23 runnable method ports sit on the same engine: ACE, GEPA, DGM, OpenEvolve,
ERA, PromptBreeder, AFlow, Reflexion, Self-Refine, TextGrad, Voyager, SkillWeaver,
Absolute Zero, R-Zero, Agent0, SICA, Gödel Agent, Genesis, RRSI and more. Each
declares its own Strategy / Policies / optimizer and its fidelity class; they are
examples of the engine, not the engine's limit.

## Interfaces

`agentdescent` ships a CLI (`demo`, `init`, `plan`, `evolve`, `status`, `watch`,
`show`, `apply`, `cancel`, `resume`, `campaign`, `tournament`, `diagnose`, `rsi`,
`safety`, `audit`, `serve`, `mcp`, ...), an MCP server, and plugins for Claude
Code, Codex, OpenCode and DSH. `EvolveSpec` makes a run a JSON document;
`RunManifest`, `DecisionLog` and `Trajectory` make it reproducible.

## Applying it to evolving Skills and Workflows

A platform that stores skills/workflows as files can use AgentDescent as the
engine and governance layer without writing another RSI loop:

| Platform object | AgentDescent |
|---|---|
| Skill directory / workflow files | `FileTree`, `TreeSpec`, `WorkspaceAgent` |
| Candidate generation | `runners`, `agents`, `EvolveSpec` |
| CI tests, lint, evals | `verifier`, `verifier_ensemble`, `evalops` |
| Real failures / PR traces | `DataFlywheel`, `TaskFoundry`, `TaskPipeline` |
| Cross-version metrics | `stats_eval`, `conformal`, `sequential` |
| Promotion | `trust_evidence`, `promotion`, `promotion_ledger` |
| Capability library | `QualityDiversityArchive`, `ArtifactGraph`, `CapabilityArchive` |
| Continual learning | `ExperienceEngine`, `continual_meta` |
| Operations | `durable_runs`, `workspaces`, `ops_fabric`, `lineage` |
| Safety | `safe_selfmod`, `proofs`, `policy_release`, `governance` |

A defensible rollout:

1. **Read-only evaluation.** Wrap one skill/workflow directory as `FileTree`,
   use CI/evals as reward, run `evolve` in a throwaway worktree, write nothing.
2. **Evidence-gated promotion.** Add `evalops` + `verifier_ensemble` +
   `trust_evidence`; let `promotion` decide promote/defer/reject. Auto-open PRs
   only for low-risk changes; defer the rest.
3. **Continual operation.** Add `durable_runs` + `workspaces` + `ops_fabric`,
   `task_pipeline` for failure-driven tasks, `capability_archive` for the skill
   library, and `experience` for cross-cycle memory.
4. **Governed autonomy.** Add `promotion_ledger` + `policy_release` + `proofs` +
   canary/rollback and `calibrated_deferral` for answer/defer/deny routing.

Do not use a single LLM judge as the only merge gate. Do not let candidates edit
the evaluator, CI configuration or frozen policy. Do not accept on a point
estimate alone; use a held-out set and a statistical gate. Do not put unbounded
experience into a prompt.

## Boundaries

`durable_runs` is a single-machine SQLite vertical slice, not a distributed
scheduler. `safe_selfmod` is a policy gate; execution still needs the sandbox /
OS boundary. Conformal and sequential guarantees have assumptions
(exchangeability, bounded deltas). The method ports have different fidelity
classes. The newer experience/preference/counterfactual layers still need
long-run validation on real traces.

The point of the framework is not more modules. It is one composable loop:
**artifact → diff → evidence → gate → ledger → experience**, with every layer
replaceable and every accepted change accountable.
