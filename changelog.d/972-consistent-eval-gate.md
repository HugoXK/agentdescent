Fixed
`EvalOps.run()` now uses the default regression gate to set `passed`, so a
single-task result no longer reports a pass that `EvalOps.gate()` rejects.
Explicit gates that disable significance checks remain available.
