"""The published evidence cards in ``reports/evidence`` stay complete (#951).

``tools/evidence_card`` is the schema and the checker; these tests pin the
cards that are actually published, so a claim cannot ship a card with a blank
or missing field and the #1042 leaf-write-through card keeps naming the code
and the regression test a reader needs to re-run it.

Two of the cards are headline results from ``reports/`` -- the audit's constant
rubric tying the judge, and the 177-pair verifier bias. Their fields are facts
about files in this repository, so they are pinned here rather than trusted.
"""
import json
import re
from pathlib import Path

import pytest

from tools import evidence_card

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "reports" / "evidence"

#: The cards that carry a headline result a reader is meant to check.
HEADLINE_CARDS = ("audit-always-no-ties-the-judge.json",
                  "audit-177-pair-verifier-bias.json")


def _published():
    return sorted(EVIDENCE.glob("*.json"))


def test_the_repo_publishes_at_least_one_card():
    assert _published(), f"no evidence card under {EVIDENCE}"


def test_every_published_card_satisfies_schema_v1():
    for card_path in _published():
        card = json.loads(card_path.read_text(encoding="utf-8"))
        assert evidence_card.validate(card, card_path.name) == [], card_path.name


def test_the_1042_card_names_its_code_and_its_regression_test():
    card_path = EVIDENCE / "1042-ports-leaf-write-through.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    assert "a095a6504b92b5788c7228649577b6241a0c2939" in card["code"]
    assert "agentdescent/ports.py:97" in card["code"]
    assert "tests/test_ports_symlink_leaf.py" in card["code"]
    assert card["held_out"] == "not reviewed"


def test_the_1042_card_is_refused_by_name_when_a_field_is_removed(tmp_path, capsys):
    card = json.loads((EVIDENCE / "1042-ports-leaf-write-through.json")
                      .read_text(encoding="utf-8"))
    del card["held_out"]
    path = tmp_path / "card.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    assert evidence_card.main(["--check", str(path)]) == 1
    err = capsys.readouterr().err
    assert "held_out" in err and "missing field" in err


def test_the_repo_publishes_a_card_for_more_than_one_headline_result():
    published = {path.name for path in _published()}
    missing = [name for name in HEADLINE_CARDS if name not in published]
    assert not missing, f"no evidence card for {missing} under {EVIDENCE}"


@pytest.mark.parametrize("name", HEADLINE_CARDS)
def test_a_headline_card_quotes_the_number_it_is_about(name):
    card = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    text = card["code"] + card["reliability"]
    # The two claims rest on numbers that exist in this repository: the audit
    # records and the report computed from them. A card that loses its number
    # is a card a reader cannot check.
    needles = ("0.836",) if name == HEADLINE_CARDS[0] else ("31 of 177", "0.2203")
    for needle in needles:
        assert needle in text, f"{name} does not quote {needle!r}"
    assert "3a5d5513bbfea71b75911add4fd0aa4854177e49" in text, name


@pytest.mark.parametrize("name", HEADLINE_CARDS)
def test_a_headline_card_names_a_test_that_exists(name):
    """A card's reproduction has to point at something a reader can run."""
    card = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    text = card["code"] + card["reliability"]
    named = re.findall(r"tests/[\w./-]*\.py", text)
    assert named, f"{name} names no test file"
    for path in named:
        assert (REPO / path).is_file(), f"{name} names missing test {path}"


def test_every_published_card_writes_absent_evidence_as_not_reviewed():
    for card_path in _published():
        card = json.loads(card_path.read_text(encoding="utf-8"))
        for field in evidence_card.FIELDS:
            value = card[field]
            if value == evidence_card.NOT_REVIEWED:
                continue
            # Anything not "not reviewed" has to say something, and every one of
            # the cards here starts its answer with a sentence, not a dash.
            assert len(value.split()) >= 5, f"{card_path.name}: {field} is a stub"


def test_the_policy_that_a_new_claim_needs_a_card_is_published():
    """#951 expresses the rule as a docs sentence, not as a PR-template edit."""
    readme = EVIDENCE / "README.md"
    assert readme.is_file(), f"no {readme}"
    text = readme.read_text(encoding="utf-8")
    assert "A new claim needs a card" in text
    assert "not reviewed" in text


# -- the claims the results page publishes ----------------------------------
#
# Every headline result on ``docs/results.md`` and in ``reports/`` names a card
# here. Each entry is (the page the claim came from, the anchors a reader checks
# it against): an anchor has to appear in the card *and* still be on the page,
# so editing the published number without editing the card fails.
CLAIM_CARDS = {
    "results-one-call-path.json": (
        "docs/results.md", ("0.167", "0.583", "338 calls")),
    "results-bring-your-own-agent.json": (
        "docs/evolution.md", ("0.250", "1.000", "141 s, 63 calls")),
    "results-efficiency.json": (
        "docs/results.md", ("5.8×", "2.65×", "3.6 s")),
    "results-equal-budget-hotpotqa.json": (
        "docs/results.md", ("0.800", "132", "73")),
    "results-merge-cost-lever.json": (
        "docs/results.md", ("1424", "1.39×", "1.92×")),
    "audit-judge-bias-five-workloads.json": (
        "reports/README.md", ("18.6%", "3.7%", "32.7%")),
    "audit-ground-truth-repair.json": (
        "reports/README.md", ("0.778", "0.967", "0.2549")),
    "audit-rule-search-residual.json": (
        "reports/verifier_diagnosis_f55dec40cec559f7.md",
        ("0.2421", "0.2203", "0.3812")),
}

#: Cards whose number a test below recomputes from a committed run.
RECOMPUTED_OFFLINE = ("results-equal-budget-hotpotqa.json",
                      "results-merge-cost-lever.json")

#: The words a card uses when its number came from a live model run instead.
LIVE = "not reproducible offline"


@pytest.mark.parametrize("name", sorted(CLAIM_CARDS))
def test_every_published_claim_has_a_card(name):
    assert (EVIDENCE / name).is_file(), f"no evidence card for the claim: {name}"


@pytest.mark.parametrize("name", sorted(CLAIM_CARDS))
def test_a_claim_card_quotes_the_page_it_came_from(name):
    page, needles = CLAIM_CARDS[name]
    card = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    text = card["code"] + card["reliability"]
    published = (REPO / page).read_text(encoding="utf-8")
    assert page in text, f"{name} does not name its source page {page}"
    for needle in needles:
        assert needle in text, f"{name} does not quote {needle!r}"
        assert needle in published, f"{page} no longer says {needle!r}"


@pytest.mark.parametrize("name", sorted(CLAIM_CARDS))
def test_every_claim_card_names_a_test_a_reader_can_run(name):
    card = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    text = card["code"] + card["reliability"]
    named = re.findall(r"tests/[\w./-]*\.py", text)
    assert named, f"{name} names no test file"
    for path in named:
        assert (REPO / path).is_file(), f"{name} names missing test {path}"


@pytest.mark.parametrize("name", sorted(CLAIM_CARDS))
def test_a_claim_card_says_what_reproduces_it(name):
    """`not reviewed` is for a field nobody measured; a measured field that no
    test here can re-run has to say so in words, because the card exists to make
    the gap between "we measured it" and "you can check it" visible."""
    card = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    text = card["code"] + card["reliability"]
    if name in RECOMPUTED_OFFLINE:
        assert "offline" in text, f"{name} is recomputed offline but does not say so"
        assert LIVE not in text, f"{name} is recomputed here but claims otherwise"
    else:
        assert LIVE in text, f"{name} hides that its number came from a live run"


def test_the_equal_budget_card_is_recomputed_from_the_committed_run():
    """The card's 'no separation' is the module's own verdict, not a reading."""
    from agentdescent.baselines import ArmResult, compare

    payload = json.loads(
        (REPO / "bench/results/equal-budget-hotpotqa-3seed.json")
        .read_text(encoding="utf-8"))
    arms = [ArmResult(arm=a["arm"], seed=a["seed"], width=a["width"],
                      rollouts=a["rollouts"], calls=a["calls"],
                      prompt_tokens=a["prompt_tokens"],
                      completion_tokens=a["completion_tokens"],
                      wallclock=a["wallclock"],
                      wallclock_parallel=a["wallclock_parallel"],
                      dev_reward=a["dev_reward"],
                      test_reward=a["test_reward"],
                      test_oracle=a["test_oracle"])
            for a in payload["arms"]]
    comparison = compare(arms, fixed="rollouts")
    assert payload["budget"]["rollouts"] == 9 and payload["fixed"] == "rollouts"
    assert comparison.unequal == [], "the arms did not get the budget they were given"
    assert comparison.spread("serial") == (0.65, 0.70, 0.85)
    assert comparison.spread("fork-of-3") == (0.70, 0.70, 0.75)
    assert comparison.spread("merge-of-3") == (0.60, 0.80, 0.85)
    assert not comparison.separates("merge-of-3", "serial")
    assert not comparison.separates("merge-of-3", "fork-of-3")


def test_the_merge_cost_card_is_recomputed_from_the_committed_cells():
    from bench import matrix_report

    payload = json.loads(
        (REPO / "bench/results/matrix-gepa-b16-w8-seed0-clean.json")
        .read_text(encoding="utf-8"))
    table = matrix_report.render(payload)
    # The page's numbers are this file's, net of time lost in failed calls: the
    # serial cell's raw 2148.4 s carries 723.6 s inside two timed-out calls.
    assert "1425 s" in table
    assert "1.39×" in table and "1.92×" in table
    card = json.loads((EVIDENCE / "results-merge-cost-lever.json")
                      .read_text(encoding="utf-8"))
    text = card["code"] + card["reliability"]
    for needle in ("1424.8", "723.6", "1.39", "1.92", "70"):
        assert needle in text, needle


def test_the_evidence_directory_indexes_every_card():
    """A card nobody links is a card nobody reads: `reports/evidence/README.md`
    is the index, and `docs/results.md` points a reader at it."""
    index = (EVIDENCE / "README.md").read_text(encoding="utf-8")
    missing = [path.name for path in _published() if path.name not in index]
    assert not missing, f"cards missing from the index: {missing}"
    results = (REPO / "docs" / "results.md").read_text(encoding="utf-8")
    assert "reports/evidence" in results
