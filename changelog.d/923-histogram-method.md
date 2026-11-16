Fixed
`export_metric()` sent histograms through the counter's `add`, so the first real
export of an `agentdescent_rsi_round_reward` raised `AttributeError` out of
`export_run`. Histograms now call the SDK's `Histogram.record()`, and the fake
SDK gives each instrument kind only its own method, so the same mistake fails in
the offline suite instead of on a host's first run (#923).
