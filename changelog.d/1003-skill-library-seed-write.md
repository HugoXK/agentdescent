Fixed
`init` / `algorithms run --kind skill_library` on a target that cannot be
written now exits 2 with one `error: cannot write <path>: <reason>` line (or
`{"ok": false, "error": ...}` under `--json`) instead of a traceback, and the
`--out` directory is proven writable before the starter skills are seeded, so a
refused run leaves no partially created `*/SKILL.md` behind.
