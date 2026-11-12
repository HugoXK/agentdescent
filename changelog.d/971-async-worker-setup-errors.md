Fixed
Async runs now record workers that fail during initialization, task selection
or completion bookkeeping, and stop with an error when every worker has
retired. Caller contract errors propagate to the calling thread; rollout
backend retries and healthy workers keep their existing behavior (#971).
