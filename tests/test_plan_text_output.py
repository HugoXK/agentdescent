"""``plan`` without ``--json`` prints a human summary, not the plan document (#919).

``demo`` already prints ``plan: 12 tasks, 4 rounds x 2 workers, up to 68 agent
calls``; ``plan`` dumped ``plan_payload`` verbatim, so on a normal spec the call
count sat ~90 lines down and the small-held-out sentence was only a string
inside ``"notes"``. The human form is the default; ``--json`` is the unchanged
machine form.
"""

import json

import pytest

from agentdescent import cli
from agentdescent.cli import plan_payload
from agentdescent.evolvespec import load_spec


def _spec(tmp_path, n=8, **evolve):
    rows = [{"prompt": f"q{i}", "gold": f"a{i}"} for i in range(n)]
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Answer.\n", encoding="utf-8")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({
        "kind": "text", "target": str(prompt),
        "data": {"path": str(cases)}, "score": "contains",
        "agent": "echo", "reflect": "echo",
        "evolve": {"rounds": 1, "n_workers": 1, "seed": 0, **evolve},
    }), encoding="utf-8")
    return str(path)


def _prompt_and_cases(tmp_path, n=8):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("be terse\n", encoding="utf-8")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": f"a{i}"}) + "\n"
        for i in range(n)), encoding="utf-8")
    return prompt, cases


def test_plain_plan_is_short_and_human(tmp_path, capsys):
    path = _spec(tmp_path)
    assert cli.main(["plan", path]) == 0
    out, err = capsys.readouterr()
    # Not the machine form: a JSON document cannot be parsed out of it.
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert len(out.splitlines()) <= 15, out
    assert "plan: 8 tasks (2 held out), 1 round x 1 worker, up to 11 agent calls" in out
    assert "no $ estimate: pass --usd-per-call" in out
    assert f"next: agentdescent evolve {path}" in out
    # The sentence `evolve()` warns with, as a warning a person sees on stderr.
    assert "warning: the held-out set has only 2 task(s)" in err


def test_plain_plan_first_line_names_the_algorithm_card(tmp_path, capsys):
    # The payload carries the algorithm *card*, not its name, so the first line
    # must print `algorithm=gepa (mechanism_microport)` and never the dict.
    path = _spec(tmp_path)
    doc = json.loads(open(path, encoding="utf-8").read())
    doc["algorithm"] = "gepa"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    assert cli.main(["plan", path]) == 0
    out = capsys.readouterr().out
    first = out.splitlines()[0]
    assert first == f"ok: text {doc['target']}  algorithm=gepa (mechanism_microport)", first
    assert "{" not in first and "}" not in first


def test_plain_plan_keeps_the_estimate_when_priced(tmp_path, capsys):
    path = _spec(tmp_path)
    assert cli.main(["plan", path, "--usd-per-call", "0.01"]) == 0
    out = capsys.readouterr().out
    assert "up to 11 agent calls" in out and "no $ estimate" not in out
    assert "$0.11" in out


def test_plan_warnings_reach_stderr(tmp_path, capsys):
    # A budget below the seed+one-round bound is a plan warning (#764).
    path = _spec(tmp_path, n=12)
    assert cli.main(["plan", path, "--budget", "0.05", "--usd-per-call", "0.01"]) == 0
    out, err = capsys.readouterr()
    assert "warning: " in err and "between rounds" in err and "overshoot" in err
    # A 12-task spec holds out 4, so the held-out sentence is not a warning here.
    assert "held-out set has only" not in err
    # Notes stay notes, not warnings.
    assert "note: " not in err


def test_plain_plan_next_keeps_an_ad_hoc_algorithm(tmp_path, capsys):
    # `--algorithm` overrides the spec in memory only, so `next:` must carry it.
    path = _spec(tmp_path)
    assert cli.main(["plan", path, "--algorithm", "gepa"]) == 0
    out = capsys.readouterr().out
    assert f"next: agentdescent evolve {path} --algorithm gepa" in out


def test_plan_json_is_unchanged(tmp_path, capsys):
    path = _spec(tmp_path)
    assert cli.main(["plan", path, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    expected = plan_payload(load_spec(path))
    assert payload == json.loads(json.dumps(expected, default=str))
    assert payload["estimate"]["agent_calls_upper_bound"] == 11


def test_algorithms_run_plain_ends_with_the_human_form(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    prompt, cases = _prompt_and_cases(tmp_path)
    out_path = tmp_path / "agentdescent.gepa.spec.json"
    assert cli.main([
        "algorithms", "run", "gepa", str(prompt), str(cases),
        "--model", "m", "--base-url", "https://example.test/v1",
        "--rounds", "1", "--workers", "1", "--out", str(out_path),
    ]) == 0
    out, err = capsys.readouterr()
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert f"wrote {out_path}" in out
    assert "plan: 8 tasks (2 held out), 1 round x 1 worker, up to 11 agent calls" in out
    assert f"next: agentdescent evolve {out_path}" in out
    assert "warning: the held-out set has only 2 task(s)" in err
    assert not (tmp_path / ".agentdescent" / "runs").exists()


def test_algorithms_run_json_stays_one_object(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    prompt, cases = _prompt_and_cases(tmp_path)
    out_path = tmp_path / "s.json"
    assert cli.main([
        "algorithms", "run", "gepa", str(prompt), str(cases),
        "--model", "m", "--base-url", "https://example.test/v1",
        "--rounds", "1", "--workers", "1", "--out", str(out_path), "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["estimate"]["agent_calls_upper_bound"] == 11
    assert "_stage" not in payload and "_plan" not in payload
