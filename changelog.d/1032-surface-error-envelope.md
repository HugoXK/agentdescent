Changed
A product-surface refusal prints one `error: <message>` line — the same envelope
the `cannot write` writers use — instead of prefixing `SurfaceError:`, and the
`--json` `error` field drops the prefix too. Any other exception keeps its class
name (#1032).
