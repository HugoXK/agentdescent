# Run manifest — what made this run reproducible

A run is reproducible only if the spec, data, model configuration and code that
produced it are identifiable. `RunManifest` hashes those inputs into one stable
id plus a field-by-field record; `verify_manifest` says which input changed.

```python
from agentdescent import build_manifest, verify_manifest

manifest = build_manifest(
    spec,
    data_paths=[spec.data["path"]],
    model_config={"model": "m", "api_key": "sk-..."},
    code_version="0.9.0")
manifest.manifest_id
changed = verify_manifest(spec, manifest, data_paths=[...], code_version="0.9.0")
```

- **Spec** is the canonical `spec.to_dict()` hash.
- **Data** is a sorted set of content hashes (a directory is a sorted relative
  path/content tree), so identical bytes in a different directory share the
  hash; absolute paths are kept only as informational metadata, and a missing
  path is recorded explicitly.
- **Model config** is canonical JSON with secret-named keys (`api_key`,
  `access_token`, `token`, `password`, ...) and obvious secret value patterns
  (`Bearer ...`, `sk-...`, `api_key=...`) redacted before hashing; the raw
  secret is never stored. A normal key like `max_tokens` is **not** redacted.
- **Seeds/algorithm/code version** are explicit fields; `extra` is redacted and
  hashed.
- **`policy_digest`** is the don't-decide-this-twice half: the decision procedure
  that judged the run
  ([`policy_digest()`](policies.md#which-version-of-this-bundle-is-a-run-using)),
  recorded beside the id and **not** inside it. The id describes the inputs; the
  policy describes what was done with them, and folding the policy in would give
  the same data two ids and make every existing manifest incomparable.
  `diff_manifest` ignores it for the same reason — `verify_manifest` cannot
  re-derive a procedure from a run's inputs.
- `manifest_id` is the hash of those fields, so two runs with identical inputs
  share it. `diff_manifest` / `verify_manifest` return the changed field names,
  which is what a replay/audit report needs.

A manifest is metadata only: it contains no artifact and no secret. Store it
beside a decision record or in a run directory.

## Replay fidelity — what the manifest cannot see

Two runs can share a manifest and still diverge: the RNG state, the harness's own
hidden state and the environment are not hashed by it. `replay_eligible` and
`replay_notes` record whether those inputs were captured, so a replay or
counterfactual claim is scoped to what exists instead of what one would like to
have.

```python
from agentdescent import (EnvironmentFingerprint, ReplayFidelity, RngRecord,
                          build_manifest, rng_digest)

fidelity = ReplayFidelity.capture(
    environment=EnvironmentFingerprint.capture(tools={"pytest": "9.2.0"}),
    rng=[RngRecord("start", rng_digest(seed="7")),
         RngRecord("interaction:3", rng_digest(seed="7", state={"calls": 3}))],
    hidden_state={"tool:sqlite": {"cursor": 12}},   # digested, never stored
    uncaptured=())                                  # empty == every source known

manifest = build_manifest(spec, data_paths=[spec.data["path"]], replay=fidelity)
manifest.replay_eligible   # True only when nothing was left uncaptured
manifest.replay_notes      # what is missing, in words
```

- **Environment** is `EnvironmentFingerprint`: cwd, interpreter, OS, the tool
  versions the caller resolved, and the **names** of the allowlisted environment
  variables that were present plus their count -- `PYTHONHASHSEED`, `PYTHONPATH`,
  `LANG`, `LC_ALL`, `TZ`, `OMP_NUM_THREADS`. No value material is stored, hashed
  or otherwise; a caller cannot widen the allowlist, and a name that looks like a
  credential is refused even when passed explicitly.
- **RNG** is one `RngRecord` per interaction boundary; `rng_digest()` refuses to
  build one from neither a seed nor a state summary, because "captured nothing"
  must not be recorded as if it were captured.
- **Hidden state** is digested through `content_digest()`. A harness that exposes
  nothing says so in `uncaptured`, which makes the record ineligible instead of
  guessing.
- `replay_eligible` never enters `manifest_id`: the id is the inputs that make two
  runs the same run, while the capture is a property of the record kept about one
  of them. A manifest built without a capture is `replay_eligible=false` with a
  note that says it was not captured — never a silent "reproducible".
- `ReplayLab(manifest=...)` refuses `counterfactual()`, `leave_one_out()` and
  `shapley()` with `ReplayNotEligible`, naming what was not reconstructed;
  `baseline()` (scoring what happened) is not a counterfactual claim and still
  works. `replay_check(captured, replayed)` compares two records' fidelity,
  reward, output and event signature — and refuses the comparison outright when
  either side was not captured.

The trajectory store carries the same object: `Trajectory.replay` round-trips
through `TrajectoryStore`, and `replay_eligible` / `replay_notes` are properties
on the trajectory itself, so an `EvidenceCard.trace_ids` entry points at a record
that says whether it can be replayed.
