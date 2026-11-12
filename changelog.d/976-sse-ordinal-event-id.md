Fixed
`agentdescent serve` SSE round events (`GET /api/runs/<id>/events`) now emit each row's 0-based append ordinal in `rounds.jsonl` as the event `id:` instead of `row["round"]`, keeping `round` in `data` and ensuring resumed runs and `Last-Event-ID` reconnects never skip rows (#976).
