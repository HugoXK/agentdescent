Fixed
`agentdescent capability init` writes the spec before the demo traces, so an
`--out` that is an existing directory fails at exit 2 without leaving a
`capability-traces.jsonl` in its parent. The staged traces are flushed and
`fsync`ed before the rename, and a `KeyboardInterrupt` while they are written
removes the temporary file instead of leaving a `.staging-*.jsonl` behind
(#1046).
