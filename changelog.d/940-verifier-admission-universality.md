Added
`VerifierAgreement.admission_report()` now measures the cross-prompt error
overlap of the accepted stratum: the share of audit prompts on which a commit
the verifier accepted is oracle-denied, reported as `repeat_overlap`, with
`high_universality` at half the prompts over three audited accepts. A high
overlap blocks the admit the mean gains would allow; an unmeasurable one (a
single prompt, or a thin sample) stays `None` and never reads as zero (#940).
