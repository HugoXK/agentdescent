Added
A promotion decision now sees what reviewing the change costs a human: the new
`ReviewCost` records the diff's files, lines, blast radius, coarse risk tier and
evidence count and estimates review minutes from documented constants, and
`PromotionRules` gains the opt-in `max_review_cost` / `max_review_minutes` limits
(both default off, so with them unset the decision and its hashes are unchanged)
that defer a disproportionate change and recommend batching it. The decision's
evidence reports `attention_per_accepted_gain` when a cost and a positive eval
delta are present (#950).
