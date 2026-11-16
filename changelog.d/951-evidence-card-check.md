Added
`python -m tools.evidence_card --check` validates the 12-field evidence card
schema v1 over the named `*.json` cards, and refuses a missing, unknown or blank
field by name; `not reviewed` is the explicit way to say a field has no evidence
(#1025).
