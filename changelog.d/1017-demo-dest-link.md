Fixed
`agentdescent demo --dir` now refuses a symlink planted at a fixture leaf or at
`spec.json` instead of following it: the run exits `2` with
`cannot write …: '<leaf>' is a symlink` before the first byte, so the demo's
bytes can no longer land outside `--dir` or overwrite the file the link points
at. The check is `filetree.dest_problem`, the same rule `init` (#1008) and the
tree writer (#977) use, and a link above `--dir` is still allowed (#1017).
