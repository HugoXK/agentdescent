Security
Span values are redacted at the boundary that carries them out of the process:
`set_attribute`, `add_event`, a span's initial `attributes`, a directly
constructed `TelemetrySpan`, a `MemoryOperation.to_span_attributes()` and the
`exception` event's message now pass through the same key/value filter, so a
credential in a precondition, verifier, event detail or raised error is written
as `[redacted]` (#1063).
