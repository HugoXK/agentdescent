Added
Memory operation telemetry: `memory.read` / `memory.write` / `memory.update` /
`memory.forget` spans with lesson provenance (precondition, evidence hash,
source trace ids, verifier, expected effect), plus a memory audit block on the
telemetry and experience reports that counts each operation, flags lessons
without provenance, and lists forgotten or rolled-back lessons with a reason and
attributable regressions (#947).
