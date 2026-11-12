"""The UTF-8 text protocol used by agent, runner and grader subprocesses."""


def decode_output(data: bytes) -> str:
    # Binary pipes keep decode failures on the calling thread on Windows.
    # Retain the universal-newline behavior of the former text-mode pipes.
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
