Fixed
`append_provenance` keeps its records in the ledger's `.git/` directory instead
of the artifact work tree, so `git add -A` can no longer sweep provenance files
(and their `.lock`) into an artifact commit; an `artifact_id` containing a path
separator, `..` or an absolute prefix is rejected instead of escaping the
provenance root (#966).
