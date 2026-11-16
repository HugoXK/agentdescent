Added
`agentdescent.facade` is the versioned import surface for embedding the engine:
a curated `__all__` covering Path A and the durable `LoopKernel` path, with
`API_VERSION = "1"` and a promise that changes are additive within a version and
removals need a bump. `tests/test_facade.py` pins the list, so widening or
narrowing it is a deliberate edit rather than an accidental import; nothing
outside the list — including the package root's research exports — is covered
(#920).
