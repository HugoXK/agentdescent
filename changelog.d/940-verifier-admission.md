Added
Verifier admission on both strata: `VerifierAgreement(rejected_sample_rate=...)`
audits a sample of the commits it rejected, and `admission_report()` reports
precision on the accepted stratum with its bootstrap interval and
`rejection_accuracy_{lower,upper}`, the interval on the share of rejections that
were correct, so a verifier that rejects good work no longer scores 1.0 on
precision alone. A demote needs a bound already under 0.5 on a stratum with at
least three audited decisions, an admit needs both pessimistic bounds at 0.8, and
a thin sample defers. `require_verifier_admission=True` carries it on
`EnsembleReport.admission`: missing, incomplete or insufficient defers, `reject`
fails closed (#940).
