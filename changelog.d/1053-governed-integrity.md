Changed
`agentdescent governed-harness` accepts a caller-supplied `integrity` pair and
passes it to `govern_harness_change`, so a spec whose after-state reorders the
guardrail path, drops an allow rule, loses a decision record or changes the
action set without declaring it is rejected before proof, approval and
promotion instead of silently skipping the composition check (#1053).
