Added
An `otel-wire` CI leg installs the `[otel]` extra and exports one span and one
metric to a closed port on `127.0.0.1`, asserting a refused connection is logged
and contained rather than raised out of `export_run`. A test pins that
`export_span` copies `ExportedSpan.attributes` verbatim — it filters and invents
nothing — so the no-content guarantee is `export_run`'s and the caller's for
spans built by hand (#1083).

The leg also keeps the fail-fast row real where the extra is installed: the SDK
import is halted through the interpreter's own `sys.modules` marker instead of a
probe-and-skip, so construction still has to name the install line, and the
loopback endpoint rows assert the accepted endpoint on a stubbed seam rather than
building a live provider. `docs/metrics.md` now says credentials go in
`OTEL_EXPORTER_OTLP_HEADERS`, never in the URL (#1083).
