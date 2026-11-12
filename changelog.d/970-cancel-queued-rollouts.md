Fixed
`evolve()` cancels workers still waiting for a concurrency slot when their round
times out, so they cannot start new rollouts after the round or run has ended.
Calls already in flight may still finish (#970).
