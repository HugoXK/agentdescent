Fixed
The review skill now takes the merge lane the diff's risk tier gives it: a T0/T1
pull request is still auto-merged pinned to the reviewed tip, while a T2/T3 one
gets `awaiting-approval` and waits for the maintainer's click instead of being
auto-merged by an agent (#961).
