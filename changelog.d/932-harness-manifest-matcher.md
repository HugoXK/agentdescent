Fixed
`agentdescent harness check` and the `FileTree` it configures now share one
matcher (`filetree.match_any`), so a manifest cannot mean two different things
on the two surfaces. Every matching component applies -- read-only wins over
editable and a frozen catch-all can no longer be hidden behind an earlier one --
budgets are charged to each matching component, and `*` no longer crosses `/`
(`**` means any depth) (#932).
