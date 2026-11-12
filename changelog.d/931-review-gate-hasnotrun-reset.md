Fixed
The review gate no longer treats a later `Ran:` / `What I ran:` block as
strong just because an earlier block in the same body had a `Not run:` line;
`hasNotRun` now resets when a later list starts, the same way `ran` already
does (#931).
