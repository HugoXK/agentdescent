Added
`FailureStratifiedSampler` stratifies tasks by base failure signature, keeps
search/select/final sets disjoint, and reports stratum coverage, overlap and
transfer status so one dominant failure mode cannot take over the search set
(#946). It is exported from the package root, the transfer comparison keeps a
float floor so equal means report `holds`, and the pick refusal names the
supported wiring (`tasks=sampler.split().search`).
