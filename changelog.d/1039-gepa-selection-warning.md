Fixed
`plan` no longer warns that `n_workers` is "best-of-N selection" for
`algorithm: gepa`: its Pareto pool admits every surviving proposal, so the
"collapse to one candidate / name a `reflect` model" advice did not apply on
the aggregator_factory path (#1039).
