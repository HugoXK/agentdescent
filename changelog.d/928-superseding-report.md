Fixed
The review gate now orders comments and reviews together by time and lets the
newest report at a tip decide, so a same-tip follow-up with no `Verdict:` line
(a withdrawal, an added requirement, an open question) voids an earlier PASS
there instead of leaving it counting. A report that names another tip is still
judged against that tip, a newer PASS still counts, and the `Ran:` / `Not run:`
handling for the winning PASS is unchanged (#928).
