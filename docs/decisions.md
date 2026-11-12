# Decision log — one immutable record per adoption

The engine keeps the artifact (ledger), the evidence (trajectory, candidates,
audit) and the run (runstore). A product also needs the **decision** as one
object: what was proposed, what the guard said, what evidence and cost it saw,
and which decision it descends from.

```python
from agentdescent import DecisionLog

log = DecisionLog("~/.agentdescent/decisions.jsonl")
record = log.record(
    kind="adoption", artifact_id="skill", diff_id="d1",
    accepted=False, category="leakage:gold",
    evidence={"leaked": ["321"]}, cost={"calls": 12})
print(log.children(record.record_id))
```

`DecisionRecord` fields: `record_id`, `kind`, `artifact_id`, `diff_id`,
`accepted`, `category`, `detail`, `evidence`, `cost`, `parent_id`, `created_at`,
`policy_digest`.
`DecisionLog` is append-only JSONL with `record`, `append`, iteration, `get`,
`children` and `count`. Malformed lines (including valid JSON that is not an
object) are skipped rather than crashing an audit, non-finite floats are written
as `null`, and a torn final line is closed before the next append so it cannot
swallow a new record. `record_id` is the primary key: `append` refuses a
duplicate. Writers in one process share a per-path lock; separate processes need
an external lock.

This is a building block: the engine does not yet write decisions on the
adoption path by itself. `get`, `children` and `count` scan the file, which is
the right trade for an audit log of this size and not for a high-QPS stream.

`parent_id` is what makes a run a tree: a session decision points at the
previous session, an adoption at the session that created it. That is the link a
dashboard, a replay tool or an audit export needs.

`policy_digest` is the other axis: **which decision procedure** produced the
record ([`policy_digest()`](policies.md#which-version-of-this-bundle-is-a-run-using)).
It is recorded exactly as the caller gives it and stays empty when the caller
does not say — the shipped bundle's digest would be a false claim on any run that
injected its own policies, and the log could no longer tell those runs apart.
`runtime.run_guarded()` passes the digest its `EvolutionResult` carries. When the
digest differs from the previous record for the same artifact, the new record
points at that earlier one and carries
`evidence["policy_change"] = {"from": …, "to": …}`, so "these commits were
admitted under the old rule" is one lookup. An unchanged digest — or an absent
one — leaves the record unparented: the chain is the policy history, not every
append.
