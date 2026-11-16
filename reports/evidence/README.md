# Evidence cards

One card per empirical claim, twelve questions, machine-checkable. The schema
and its checker are `tools/evidence_card.py`; the twelve fields are the ones
`#951` lists, and the only way to say a field has no evidence is the string
`not reviewed`.

**A new claim needs a card.** Any pull request, report or doc page that adds a
headline result adds a card here in the same change. The card is what a reader
uses to see the gap: a field reading `not reviewed` is a statement that nobody
measured it, which is more useful than the claim not saying so.

Every card is checked in CI, and `tests/test_evidence_card_reports.py` pins each
published card's own anchors — the numbers it quotes and the test that
reproduces them — so a card cannot drift away from the result it describes. The
two bench cards are recomputed there from the committed runs; the rest name the
command and the live run that produced them.

## The cards

| card | the claim it covers | where it was published |
|---|---|---|
| [`results-one-call-path.json`](results-one-call-path.json) | one `evolve()` call moves held-out `0.167` → `0.583` | [results](../../docs/results.md) |
| [`results-bring-your-own-agent.json`](results-bring-your-own-agent.json) | an existing agent, `0.250` → `1.000` in one round | [evolution](../../docs/evolution.md) |
| [`results-efficiency.json`](results-efficiency.json) | parallel speedups `5.8×` / `1.8×` / `1.7×` / `2.65×` | [results](../../docs/results.md) |
| [`results-equal-budget-hotpotqa.json`](results-equal-budget-hotpotqa.json) | merge vs fork at equal rollouts: no separation | [results](../../docs/results.md) |
| [`results-merge-cost-lever.json`](results-merge-cost-lever.json) | merging as a cost lever, `1.39×` / `1.92×` | [results](../../docs/results.md) |
| [`audit-judge-bias-five-workloads.json`](audit-judge-bias-five-workloads.json) | judge error `0.0%`–`32.7%` across five workloads | [reports](../README.md) |
| [`audit-ground-truth-repair.json`](audit-ground-truth-repair.json) | ground truth repairing the judge, 9 vs 30 units | [reports](../README.md) |
| [`audit-rule-search-residual.json`](audit-rule-search-residual.json) | rule search: `0.2421` against a `0.2203` floor | [diagnosis](../verifier_diagnosis_f55dec40cec559f7.md) |
| [`audit-177-pair-verifier-bias.json`](audit-177-pair-verifier-bias.json) | 31 disagreements in 177 pairs | [reports](../README.md) |
| [`audit-always-no-ties-the-judge.json`](audit-always-no-ties-the-judge.json) | a constant rubric ties the judge at `0.836` | [audit](../../docs/audit.md) |
| [`1042-ports-leaf-write-through.json`](1042-ports-leaf-write-through.json) | a link at a written leaf is refused, not followed | PR #1042 |

```sh
python -m tools.evidence_card --check          # every card in this directory
python -m tools.evidence_card --check <card>   # one card
```

Exit 0 valid, 1 refused with one line per offending field, 2 input error. A
missing field, an unknown field, a blank value or a non-string value is refused
by name; `schema_version` must be `1`.
