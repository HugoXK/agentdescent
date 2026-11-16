Added
`agentdescent.ports` adds the `EvaluationProvider` protocol and the
`CsvEvaluationProvider` reference backend, so a split and the scorer a run
optimises can come from a database or an internal judge service instead of a
file; `oracle` and `judge` report `None` rather than a score they cannot measure
(#924).
