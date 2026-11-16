Fixed
`FileArtifactStore` now refuses a regular file where a revision tree belongs and
a directory where its sidecar belongs with `ValueError` before anything is
written, instead of the raw `NotADirectoryError`/`IsADirectoryError` from the
rename; a refused sidecar no longer leaves the revision listed without one
(#1045).
