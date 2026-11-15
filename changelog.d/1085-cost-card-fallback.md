Changed
`docs/cost.md` and the `Cost.from_cards` / module docstrings now state what the
card fallback actually returns in-tree: no producer writes
`cost_tokens`/`cost_wallclock` onto an `EvidenceCard`, so `Cost.from_cards`
yields `Cost()` — unknown, not a free diff — and a caller that wants the gate to
price a diff passes `MergeContext.diff_cost = Cost.from_usage(usage)`. The page
also warns that `require_cost=True` defers every candidate on a run whose cards
carry no cost (#1085).
