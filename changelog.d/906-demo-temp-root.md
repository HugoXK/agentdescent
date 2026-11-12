Fixed
`agentdescent demo` no longer leaves an `agentdescent-demo-*` directory in the
temporary path after every bare run: the default root is removed on the success
and the error path, while `--dir` keeps the directory it names and `--json`
still reports a `dir` that exists. The quickstart line now says which case keeps
the files (#906).
