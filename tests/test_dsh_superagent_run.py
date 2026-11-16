"""The long-run handoff (#964): the page's command, and the run outliving a turn.

Two checks, and neither needs a model:

* the documented command shape is real -- the wrapper exists and takes the
  flags the page passes it, and `agentdescent evolve` still answers `--detach`,
  which is the flag the page tells a worker to use;
* gated behind ``AGENTDESCENT_LONG_RUN_SMOKE=1``, a fake run longer than the
  caller's own limit survives the caller's turn: the wrapper returns while the
  run is still going, the report names the run id and round, and no tmux
  session (hence no orphan) is left once it finishes.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agentdescent import cli, runstore

REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "scripts" / "dsh-superagent-run.sh"
PAGE = REPO / "docs" / "dsh-super-agent.md"

FAKE = '''
import json, os, sys, time
store = sys.argv[1]
run_dir = os.path.join(store, "fake-run-1")
os.makedirs(run_dir, exist_ok=True)
path = os.path.join(run_dir, "status.json")

def write(**kw):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(kw, fh)

write(run_id="fake-run-1", round=2, state="running", pid=os.getpid())
time.sleep(3)
write(run_id="fake-run-1", round=3, state="finished", pid=os.getpid())
'''


def _page_handoff_example() -> str:
    """The page's fenced example that starts a run through the wrapper."""
    page = PAGE.read_text(encoding="utf-8")
    for block in page.split("```"):
        if "scripts/dsh-superagent-run.sh" in block:
            return block
    raise AssertionError("the page has no example that starts the wrapper")


def _handoff_argv():
    """The page's example as the shell would hand it over: (wrapper, child) argv.

    Parsed, not matched as a substring. The block is a command a worker copies,
    so its flags have to be the ones the CLI accepts *as a pair* -- a
    substring check passes a command that exits 2, which is how `--budget` went
    out without its `--usd-per-call` (#1084 review).
    """
    block = _page_handoff_example()
    # The shell's line continuations, then the `#` lines showing its output --
    # both are page furniture, not arguments.
    code = block.replace("\\\n", " ")
    code = " ".join(line for line in code.splitlines()
                    if not line.strip().startswith("#"))
    argv = shlex.split(code)
    assert argv[0] == "bash", f"the example does not invoke the wrapper with bash: {argv}"
    assert "--" in argv, f"the example does not separate the wrapper's flags: {argv}"
    cut = argv.index("--")
    return argv[1:cut], argv[cut + 1:]


def _store_flag(argv) -> str:
    """The value after `--store`, which is what must agree on both sides."""
    assert "--store" in argv, f"no --store in {argv}"
    return argv[argv.index("--store") + 1]


def test_the_page_hands_the_run_the_store_the_wrapper_reports_into():
    # Two stores, one variable. The wrapper's `--store` is where the report
    # goes; the run's store is the CLI's own global flag. Naming only the
    # wrapper's store made `evolve` write to the default store, so the wrapper
    # waited out its deadline and reported found: false, and the page's
    # read-back could not find the run (#1084 review).
    wrapper_argv, child_argv = _handoff_argv()
    assert Path(wrapper_argv[1]).name == "dsh-superagent-run.sh", wrapper_argv

    # Drop the child's program name ("agentdescent", or `python -m
    # agentdescent.cli`); the CLI's own parser then says whether the rest is a
    # command it has.
    start = next((i for i, token in enumerate(child_argv)
                  if token in ("agentdescent", "agentdescent.cli")), None)
    assert start is not None, f"the example does not run agentdescent: {child_argv}"
    cli_argv = child_argv[start + 1:]
    try:
        args = cli.build_parser().parse_args(cli_argv)
    except SystemExit as e:  # argparse exits 2 on a flag the CLI does not have
        raise AssertionError(
            f"the page's handoff command is not one the CLI accepts: {cli_argv} "
            f"(exit {e.code})") from e

    assert _store_flag(wrapper_argv) == _store_flag(cli_argv), (
        "the report's store and the run's store must be the same value")
    assert getattr(args, "detach", False), "the handoff must start the run detached"
    # The section promises a run that stops itself and writes why, which is what
    # --budget buys; the CLI refuses that flag without a per-call price.
    assert args.budget is not None, (
        "the section documents a capped run, so the example carries --budget")
    assert args.usd_per_call, (
        f"the page passes --budget {args.budget} without --usd-per-call, so the "
        "documented command exits 2 and starts nothing")
    runstore.require_budget_pair(args.budget, args.usd_per_call)


def test_the_page_documents_a_wrapper_that_exists_and_takes_its_flags():
    assert WRAPPER.is_file(), f"no {WRAPPER}"
    # Invoked as `bash scripts/dsh-superagent-run.sh`, the way the page and
    # `scripts/verify-dsh-superagent.sh` (committed 644) are, so the mode is not
    # part of the contract; the command shape below is.
    page = PAGE.read_text(encoding="utf-8")
    assert "scripts/dsh-superagent-run.sh" in page, "the page does not name the wrapper"
    assert "--store" in page and "--detach" in page
    helped = subprocess.run(["bash", str(WRAPPER), "--help"], cwd=REPO,
                            capture_output=True, text=True, timeout=60)
    assert helped.returncode == 0, helped.stderr
    assert "--store" in helped.stdout, "the wrapper's usage omits --store"
    evolve = subprocess.run(
        [sys.executable, "-m", "agentdescent.cli", "evolve", "--help"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert evolve.returncode == 0, evolve.stderr
    assert "--detach" in evolve.stdout, "the page tells a worker to pass a flag the CLI dropped"


def _path_without_tmux(base: Path) -> str:
    """A PATH holding the wrapper's tools and no `tmux` (the fallback row).

    The setsid row has to reach the fallback on a host that has tmux installed,
    so `command -v tmux` must fail without also removing bash or python3.
    """
    shim = base / "shim"
    shim.mkdir()
    for tool in ("bash", "sh", "basename", "tr", "mkdir", "python3", "setsid",
                 "sleep", "rm"):
        found = shutil.which(tool)
        assert found is not None, f"the wrapper needs {tool}, which this host lacks"
        os.symlink(found, shim / tool)
    return str(shim)


@pytest.mark.parametrize("driver", ["tmux", "setsid"])
def test_a_store_path_with_shell_metacharacters_hands_off_without_running_them(
        tmp_path, driver):
    # The launch command used to be built as a shell string with the log path
    # spliced in as `>> '$LOG'`: an apostrophe in --store closed the quote, and
    # the rest of the path became shell words run outside the worker's process
    # group with the operator's privileges (#1109). The path below carries an
    # apostrophe, a semicolon, spaces and a dollar sign.
    pwned = tmp_path / "PWNED"
    store = tmp_path / f"it's; > {pwned}; echo '$HOME"

    env = dict(os.environ, DSH_RUN_HANDOFF_WAIT="1")
    if driver == "tmux":
        if shutil.which("tmux") is None:
            pytest.skip("no tmux on this host: the session row cannot run")
    else:
        if shutil.which("setsid") is None:
            pytest.skip("no setsid on this host: the fallback row cannot run")
        env["PATH"] = _path_without_tmux(tmp_path)

    # The child writes a marker, so "the run started" is measured rather than
    # inferred from a log file the redirection alone would have created.
    marker = tmp_path / "ran.txt"
    child = [sys.executable, "-c",
             "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('ran\\n')",
             str(marker)]
    handed = subprocess.run(
        ["bash", str(WRAPPER), "--store", str(store), "--"] + child,
        cwd=REPO, capture_output=True, text=True, timeout=60, env=env)

    assert handed.returncode == 0, handed.stderr
    assert not pwned.exists(), (
        f"the --store path ran as shell code and created {pwned}; "
        f"wrapper stderr: {handed.stderr!r}")
    report = json.loads((store / "waiting.json").read_text(encoding="utf-8"))
    assert report["driver"] == driver, report
    assert report["log"] == str(store / "worker.log"), report
    assert report["command"].strip().startswith(sys.executable), report
    # `waiting.json` is the page's contract; a quoting fix must not rename, add
    # or drop a field the read-back documents.
    assert set(report) == {"status", "found", "run_id", "round", "state",
                           "run_dir", "driver", "session", "log", "command"}
    assert (store / "worker.log").is_file(), report
    assert marker.read_text(encoding="utf-8") == "ran\n", (
        f"the run did not start through the handed-off log: {report}")


@pytest.mark.skipif(os.environ.get("AGENTDESCENT_LONG_RUN_SMOKE") != "1",
                    reason="set AGENTDESCENT_LONG_RUN_SMOKE=1 to run the detached smoke")
def test_a_run_outlives_the_turn_that_started_it_and_leaves_no_orphan(tmp_path):
    store = tmp_path / "runs"
    fake = tmp_path / "fake_run.py"
    fake.write_text(FAKE, encoding="utf-8")

    started = time.monotonic()
    handed = subprocess.run(
        ["bash", str(WRAPPER), "--store", str(store), "--",
         sys.executable, str(fake), str(store)],
        cwd=REPO, capture_output=True, text=True, timeout=60)
    elapsed = time.monotonic() - started

    assert handed.returncode == 0, handed.stderr
    assert elapsed < 2.0, f"the handoff blocked for {elapsed:.1f}s, so it held the slot"
    report = json.loads((store / "waiting.json").read_text(encoding="utf-8"))
    assert report["status"] == "waiting"
    assert report["found"] is True
    assert report["run_id"] == "fake-run-1"
    assert report["round"] == 2
    assert Path(report["run_dir"]).name == "fake-run-1"

    # The caller's turn is over and the run is still going: that is the handoff.
    pid = json.loads((Path(report["run_dir"]) / "status.json")
                     .read_text(encoding="utf-8"))["pid"]
    os.kill(pid, 0)

    deadline = time.monotonic() + 30
    status = {}
    while time.monotonic() < deadline:
        status = json.loads((Path(report["run_dir"]) / "status.json")
                            .read_text(encoding="utf-8"))
        if status["state"] == "finished":
            break
        time.sleep(0.2)
    assert status["state"] == "finished", status
    assert status["round"] == 3

    if report["driver"] == "tmux" and shutil.which("tmux"):
        # The run writes `finished` before its own process exits, and tmux
        # destroys the session after the pane's command ends, so the session is
        # still listed for a moment -- measured ~1.7s on a loaded host. Poll for
        # it to go; only a session that stays is an orphan. `=` asks for that
        # exact name: a bare target also prefix-matches a longer one, so
        # `-t ad-runs` can answer about an unrelated ad-runs-2.
        poll_started = time.monotonic()
        deadline = poll_started + 15
        left = 0
        while time.monotonic() < deadline:
            left = subprocess.run(
                ["tmux", "has-session", "-t", "=" + report["session"]],
                capture_output=True, text=True).returncode
            if left != 0:
                break
            time.sleep(0.1)
        waited = time.monotonic() - poll_started
        assert left != 0, (
            f"orphan tmux session {report['session']!r} still listed after "
            f"{waited:.1f}s (last `tmux has-session` rc={left})")


@pytest.mark.skipif(os.environ.get("AGENTDESCENT_LONG_RUN_SMOKE") != "1",
                    reason="set AGENTDESCENT_LONG_RUN_SMOKE=1 to run the detached smoke")
def test_a_reused_store_does_not_report_an_earlier_run(tmp_path):
    # A store is reused for every Ticket, so it always holds earlier runs. The
    # first poll used to take the newest `*/status.json` it could see and report
    # that run -- a finished one -- as the handoff (#1084 review). Nothing here
    # writes a status.json, so the report must say it found nothing.
    store = tmp_path / "runs"
    old = store / "old-run"
    old.mkdir(parents=True)
    (old / "status.json").write_text(
        json.dumps({"run_id": "old-run", "round": 7, "state": "finished"}),
        encoding="utf-8")
    handed = subprocess.run(
        ["bash", str(WRAPPER), "--store", str(store), "--", "sleep", "1"],
        cwd=REPO, capture_output=True, text=True, timeout=60,
        env=dict(os.environ, DSH_RUN_HANDOFF_WAIT="1"))
    assert handed.returncode == 0, handed.stderr
    report = json.loads((store / "waiting.json").read_text(encoding="utf-8"))
    assert report["found"] is False, report
    assert report["run_id"] == "", report
    assert report["round"] == 0, report
    assert os.path.realpath(report["run_dir"]) == os.path.realpath(str(store)), report


@pytest.mark.skipif(os.environ.get("AGENTDESCENT_LONG_RUN_SMOKE") != "1",
                    reason="set AGENTDESCENT_LONG_RUN_SMOKE=1 to run the detached smoke")
def test_two_handoffs_into_stores_called_runs_do_not_take_one_session(tmp_path):
    # The session name came from the store's basename, so two handoffs into
    # stores both called `runs` asked tmux for the same session and the second
    # died with "tmux refused the session" (#1084 review).
    if not shutil.which("tmux"):
        pytest.skip("no tmux on this host: the setsid fallback has no session name")
    fake = tmp_path / "fake_run.py"
    fake.write_text(FAKE, encoding="utf-8")
    reports = []
    for name in ("a", "b"):
        store = tmp_path / name / "runs"
        handed = subprocess.run(
            ["bash", str(WRAPPER), "--store", str(store), "--",
             sys.executable, str(fake), str(store)],
            cwd=REPO, capture_output=True, text=True, timeout=60)
        assert handed.returncode == 0, handed.stderr
        reports.append(json.loads((store / "waiting.json").read_text(encoding="utf-8")))
    assert reports[0]["driver"] == "tmux", reports
    assert reports[0]["session"] and reports[1]["session"], reports
    assert reports[0]["session"] != reports[1]["session"], reports

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and any(
            subprocess.run(["tmux", "has-session", "-t", "=" + report["session"]],
                           capture_output=True, text=True).returncode == 0
            for report in reports):
        time.sleep(0.1)
