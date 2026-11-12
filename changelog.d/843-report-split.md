Changed
`evolve(test_frac=...)` can carve a test partition out of the held-out tail:
accept/select keep reading the select split, the test split is scored once at
the end and reported as `test_reward`, so the printed reward is no longer the
score of the set that chose the winner. With no split, `evolve`, `show` and
`diagnose` now say plainly that the reported reward is the select set, not an
unseen test set (#843).
