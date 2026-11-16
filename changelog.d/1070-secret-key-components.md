Fixed
Telemetry exports lose no more than credentials: a key is dropped when a whole
component of it names a credential, not when it merely contains the substring
`token` or `secret`. `tokens`, `max_tokens`, `input_tokens`, `output_tokens`,
`token_count`, `tokens_in`, `budget_tokens`, `secret_free` and
`secrets_scanned` are written again (the cost and budget counters among them),
while `api_key`, `apikey`, `access_key`, `client_secret`, `private_key`,
`password`, `authorization`, `credential` and the `*_token` spellings still
drop (#1070).
