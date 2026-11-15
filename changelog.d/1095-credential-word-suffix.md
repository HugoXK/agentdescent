Fixed
`_is_secret_key` no longer lets a credential through when it arrives as one
word: `PGPASSWORD`, `s3secretkey` and `AWSSecretAccessKey` are matched by
whole-word suffix on a single-component key, and the adjacent-pair lookup
tolerates one plural `s`, so `client_secrets` and `api_keys` are dropped too.
The plural spellings (`passwords`, `pgpasswords`, `db_secrets`) match in the
last position or as a whole component. The `#1070` counters (`tokens`,
`max_tokens`, `secrets_scanned`) still survive, and `auth` stays a recorded
non-goal (#1095).
