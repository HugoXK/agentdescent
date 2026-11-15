Changed
The results and audit pages now point at evidence cards for their headline
claims: one card per claim under `reports/evidence/`, each answering all twelve
fields and writing `not reviewed` where nobody measured. Eight new cards cover
the one-call path, bringing your own agent, the efficiency rows, equal-budget
HotpotQA, the merge cost lever, judge bias across five workloads, ground-truth
repair, and the rule search's residual against the sigma floor. The directory
indexes them in `reports/evidence/README.md`, the two bench cards are recomputed
in CI from the committed runs, and the rest say on the card that their number
came from a live run — so the gap between "we measured it" and "you can check
it" is visible where the claim is (#951).
