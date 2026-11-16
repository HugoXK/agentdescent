"""The review gate binds a PASS to the tip named inside its own report (#930).

`parse_report` used to keep the last `Tip SHA:` line and the last `Verdict:`
line independently, so an appended bare `Tip SHA: <B>` re-pointed an older
`Verdict: PASS` at `<A>` onto `<B>`. The PASS then counted for a commit it
never judged, which is exactly the "the tip moved under the PASS" hole the
gate exists to close.

The four real shapes must keep working after the fix, or the fix trades one
hole for another: `#774` (verdict above its tip line), `#776`/`#782` (tip
inline in the verdict), `#905` (`Tip:` label with `What I ran (...)`), and the
normal report whose verdict closes the evidence list.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / ".github" / "agent" / "review-policy.json").read_text())
HEAD = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"
EVIDENCE = ("pytest -q → pass",)


def _mod():
    spec = importlib.util.spec_from_file_location("review_gate", ROOT / ".github" / "scripts" / "review_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _mod()


def report(verdict="PASS", tip=HEAD, ran=EVIDENCE, not_run=True):
    lines = [f"Tip SHA: `{tip}`", "Ran:"] + [f"  - {r}" for r in ran]
    if not_run:
        lines += ["Not run:", "  - Ark real-model run — no code path to a model changed"]
    return "\n".join(lines + [f"**Verdict: {verdict}**"])


def c(body, login="Birfy", at="2026-11-11T10:00:00Z", kind="comment"):
    return {"login": login, "body": body, "at": at, "kind": kind}


def test_an_appended_tip_line_does_not_repoint_an_older_pass():
    # The live shape from #930: PASS at HEAD, then a re-tip note under it.
    body = report(tip=HEAD) + "\n\n" + f"Tip SHA: `{OTHER}` (re-tipped, please re-review)"
    # The gate must not hand the older PASS to the tip the note appended: the
    # report names HEAD, so judging OTHER fails with "names HEAD, not the tip".
    moved = rg.decide(OTHER, "HugoXK", [c(body)], POLICY)
    assert not moved["ok"] and "not the tip" in moved["reason"]
    assert rg.parse_report(body)["tip"] == HEAD
    r = rg.decide(HEAD, "HugoXK", [c(body)], POLICY)
    assert r["ok"] and r["by"] == "Birfy" and r["tip"] == HEAD


def test_a_verdict_above_its_tip_line_still_counts():
    # #774, 2026-11-09: Verdict first, then the Tip SHA it is about.
    body = "\n".join([
        "**Verdict: PASS**",
        "",
        f"Tip SHA: `{HEAD}`",
        "Ran:",
        "  - pytest -q → pass",
        "Not run:",
        "  - Ark real-model run — no code path to a model changed",
    ])
    parsed = rg.parse_report(body)
    assert parsed["tip"] == HEAD and parsed["verdict"] == "PASS"
    assert rg.decide(HEAD, "Birfy", [c(body)], POLICY)["ok"]


def test_a_verdict_carrying_its_tip_inline_still_counts():
    # #776/#782, 2026-11-09: `Verdict: PASS (tip b0a30224)`, no Tip SHA line.
    head = "b0a30224" + HEAD[8:]
    body = "\n".join([
        "Ran:",
        "  - pytest -q → pass",
        "Not run:",
        "  - Ark real-model run — no code path to a model changed",
        "",
        "**Verdict: PASS (tip b0a30224)**",
    ])
    parsed = rg.parse_report(body)
    assert parsed["tip"] == "b0a30224" and parsed["verdict"] == "PASS"
    r = rg.decide(head, "HugoXK", [c(body)], POLICY)
    assert r["ok"] and r["by"] == "Birfy" and r["tip"] == "b0a30224"


def test_a_tip_label_before_what_i_ran_still_counts():
    # #905, 2026-11-09: `Verdict: PASS`, a `Tip:` line, then `What I ran (...)`.
    body = "\n".join([
        "Verdict: PASS",
        "",
        f"Tip: {HEAD}",
        "",
        "What I ran (shared venv):",
        "- tests/test_mcp.py",
        "- tests/test_demo.py",
        "",
        "Not run:",
        "  - Ark real-model run — no model path changed",
    ])
    parsed = rg.parse_report(body)
    assert parsed["tip"] == HEAD and parsed["verdict"] == "PASS"
    assert parsed["ran"] == ["- tests/test_mcp.py", "- tests/test_demo.py"]
    r = rg.decide(HEAD, "HugoXK", [c(body)], POLICY)
    assert r["ok"] and r["by"] == "Birfy" and not r["weak"]


def test_a_tip_line_after_the_evidence_is_not_part_of_the_report():
    # No tip of its own before the evidence: this report names no commit.
    body = "\n".join([
        "**Verdict: PASS**",
        "Ran:",
        "  - pytest -q → pass",
        "Not run:",
        "  - Ark real-model run — no code path to a model changed",
        "",
        f"Tip SHA: `{HEAD}`",
    ])
    parsed = rg.parse_report(body)
    assert parsed["tip"] is None and parsed["verdict"] == "PASS"
    r = rg.decide(HEAD, "HugoXK", [c(body)], POLICY)
    assert not r["ok"] and "no Tip SHA" in r["reason"]
