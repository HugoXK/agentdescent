Fixed
`build_trust_evidence(..., artifact_changed=False)` now reports `gain == 0` and
`noise_only is True` for an artifact that is byte-identical before and after,
and such a bundle can no longer return `promote`: the zeroed eval delta is not a
pass, so evaluation noise is not repriced as learning (#937).
