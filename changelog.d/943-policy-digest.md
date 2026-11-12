Added
A run, a commit and a decision can now name the decision procedure that produced
them, as a content hash over the `Policies` bundle, the decision-relevant
`AggregatorConfig` fields and the verifier's knobs:
`policy_digest` on `DecisionRecord`, `MergeContext`, `RunManifest` (`build_manifest`)
and `EvolutionResult`, plus a `policy-digest:` trailer on the ledger's commit
message. A decision taken under a different policy than the previous one for the
same artifact links to it (`parent_id` + `evidence["policy_change"]`), and
`agentdescent.policies.policy_digest()` computes the version for a hand-built
bundle, and `StableDistanceAcceptance` / `AdaptiveTrustRegion` now expose their
own knobs to it. A decision record that does not state a policy keeps
`policy_digest` empty rather than claiming the shipped default, and
`run_guarded()` records the digest its result carried. Additive: empty by
default, unchanged commit messages and unchanged `manifest_id` (#943).
