Fixed
`merge-lane` reads `review-policy.json` and `risk-rules.json` from the PR's base
commit instead of the clone it runs in, so a branch that edits either file can
no longer lend itself a PASS or a lower tier; `.github/**` and
`.claude/skills/**` are T3 by rule, and a base that cannot serve either file
prints no lane at all (#978).
