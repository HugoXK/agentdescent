Added
`agentdescent plan --probe` and `agentdescent algorithms run … --probe` send one
minimal model call per model-backed agent and reflector before a run exists, so
an expired subscription, an exhausted quota, a wrong model name or a dead
endpoint is refused there with the same `SubscriptionInactive` /
`QuotaExhausted` / `ProviderConfigError` answer `evolve` would have given — and
without a `failed round 0/1` entry in the run store. Off by default: plain
`plan` still sends nothing (#1048).
