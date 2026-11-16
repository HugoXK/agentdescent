Added
A per-diff `Cost` block (calls, tokens, wall seconds, optional USD), the
`cost_efficiency` / `cost_status` reads, a `CostPolicy` acceptance wrapper that
refuses a quality gain whose cost efficiency regressed (and defers when cost is
required but unmeasured), a `cost_report` with cost per accepted diff and per
point of gain, and `PromotionRules(require_cost=True)` (#945). A report average
is `None` unless every decision measured the unit being divided -- a row priced
in tokens only cannot make the dollar figure look cheaper than the evidence.
This also fixes the API reference for the name it exports: `docs/api.md` was
generated from a flat short-name map, so `agentdescent.Cost` was shadowed by
`agentdescent.audit.scorecard.Cost` and the page documented a signature the
top-level import does not return. The generator now keys by `(module, name)` and
`agentdescent.cost` has its own section, so both types are documented.
