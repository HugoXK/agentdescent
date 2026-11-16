Changed
`agentdescent apply` honours `AGENTDESCENT_SURFACE_WRITE_DIRS`: a destination,
a materialised tree or a `.bak-N` slot outside the allowlist is refused with
exit 2 before anything touches disk. Inside a host worker
(`AGENTDESCENT_NESTED=1`) the allowlist defaults to the run's cwd plus
`$AGENTDESCENT_HOME`; outside one it is only enforced when the variable is set,
so a terminal `apply --to <path>` behaves as before. `show --diff` still
renders and reports the refused target in `apply_plan` (#1082).
