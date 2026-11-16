"""Evidence cards: the 12-field schema and its offline ``--check`` validator.

``#951`` publishes every claim as a card, so a reader can see which of the twelve
questions it leaves unanswered. These pin the validator on temporary trees: a
complete card passes, every incomplete one is refused with the offending field
named on one line, and ``not reviewed`` is the explicit "no evidence".
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

FIELDS = ("held_out", "matched_budget", "cross_model", "cost", "disjoint_search",
          "reliability", "code", "evolved_artifact", "who_edits", "feedback",
          "timing", "topology")


def _tool():
    from tools import evidence_card
    return evidence_card


def _card(**overrides):
    card = {name: f"{name} measured" for name in FIELDS}
    card["schema_version"] = 1
    card.update(overrides)
    return card


def _write(tmp_path, card, name="card.json"):
    path = tmp_path / name
    path.write_text(json.dumps(card), encoding="utf-8")
    return path


def _check(*paths):
    return _tool().main(["--check", *[str(p) for p in paths]])


def test_a_complete_card_passes(tmp_path, capsys):
    assert _check(_write(tmp_path, _card())) == 0
    assert "1 card" in capsys.readouterr().out


@pytest.mark.parametrize("field", FIELDS)
def test_a_missing_field_is_refused_by_name(tmp_path, capsys, field):
    card = _card()
    del card[field]
    assert _check(_write(tmp_path, card)) == 1
    err = capsys.readouterr().err
    assert field in err
    assert "\n" not in err.strip(), "a refusal is one line per offending field"


@pytest.mark.parametrize("value, needle", [("", "blank"), (None, "string")])
def test_a_blank_or_non_string_value_is_refused_by_name(tmp_path, capsys, value, needle):
    assert _check(_write(tmp_path, _card(cost=value))) == 1
    err = capsys.readouterr().err
    assert "cost" in err and needle in err


@pytest.mark.parametrize("field", FIELDS)
def test_not_reviewed_is_accepted_for_every_field(tmp_path, field):
    assert _check(_write(tmp_path, _card(**{field: "not reviewed"}))) == 0


def test_a_card_of_all_not_reviewed_passes(tmp_path, capsys):
    card = {name: "not reviewed" for name in FIELDS}
    card["schema_version"] = 1
    assert _check(_write(tmp_path, card)) == 0
    assert "1 card" in capsys.readouterr().out


def test_an_unknown_field_is_refused_by_name(tmp_path, capsys):
    assert _check(_write(tmp_path, _card(confidence="high"))) == 1
    err = capsys.readouterr().err
    assert "confidence" in err and "unknown" in err


@pytest.mark.parametrize("version", [2, 0, "1"])
def test_a_wrong_schema_version_is_refused_by_name(tmp_path, capsys, version):
    assert _check(_write(tmp_path, _card(schema_version=version))) == 1
    assert "schema_version" in capsys.readouterr().err


def test_one_bad_card_fails_the_run_and_names_it(tmp_path, capsys):
    _write(tmp_path, _card(), "good.json")
    bad = _card()
    del bad["timing"]
    _write(tmp_path, bad, "bad.json")
    assert _check(tmp_path) == 1
    err = capsys.readouterr().err
    assert "bad.json" in err and "timing" in err


def test_no_paths_without_the_directory_is_zero_cards(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert _tool().main(["--check"]) == 0
    assert "0 cards" in capsys.readouterr().out
    assert not (tmp_path / "reports" / "evidence").exists(), "the check writes nothing"


def test_no_paths_scans_the_default_directory(tmp_path, monkeypatch, capsys):
    evidence = tmp_path / "reports" / "evidence"
    evidence.mkdir(parents=True)
    _write(evidence, _card())
    monkeypatch.chdir(tmp_path)
    assert _tool().main(["--check"]) == 0
    assert "1 card" in capsys.readouterr().out


def test_the_module_is_runnable_with_dash_m(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "tools.evidence_card", "--check",
         str(_write(tmp_path, _card()))],
        cwd=str(REPO), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "1 card" in proc.stdout
