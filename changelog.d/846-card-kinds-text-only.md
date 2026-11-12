Changed
A text-only Algorithm card asked to run on a `skill_library` (or any other tree
kind) now says so in the kind-mismatch error, before the list of cards that do
apply: `'gepa' is text-only: it reads a single text file, not a skill_library
target`. The list of applicable cards and the one-file `--kind text` route are
unchanged (#846).
