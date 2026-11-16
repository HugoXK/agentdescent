Added
Falsification-gated lesson admission: `FalsificationAcceptance` fills the existing
`Policies(acceptance=...)` slot and decides a commit on per-task measurements
instead of held-out counts alone. A lesson commits only with a measured gain on the
target-transfer partition, no per-task regression on the archived partition, and no
verdict change on the falsification partition; each reject reason
(`no-target-transfer`, `archived-regression`, `falsification-moved`) names the
failing task ids. Probes are caller-supplied (`MergeContext.probes`), and when they
are unavailable the policy defers (`AcceptDecision(defer=True)`) rather than falling
back to the count-only gate; all three partitions are required, and an empty one is
refused at construction instead of deferring on every candidate. A deferral under a
category this build does not know reports `probes-unavailable` rather than raising
inside the merge thread. A committed lesson hands its review evidence
(`rule_id -> {precondition, behavior_change, expected_effect, verifier, trace_ids,
evidence_card_hash}`) to the shared provenance writer as
`AcceptDecision.provenance` (#938).
