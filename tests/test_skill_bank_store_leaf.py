"""The skill-bank store leaf is a regular file (#1015).

One rule, three properties. An existing path that is not a regular file is
refused on load instead of being read as "no bank yet", because reporting
`skills: 0` and then claiming `applied: True` is a confidently wrong answer.
Every write refuses a symlink store *before* `mkstemp`, because a rename
replaces the link rather than the file it names, which leaves two files
claiming to be the bank. And `applied` reports whether a status changed, not
which flag was passed.
"""
from __future__ import annotations

import json
import os

import pytest

from agentdescent import cli
from agentdescent.skill_bank import SkillBank, SkillBankError


def _bank(path):
    bank = SkillBank(str(path))
    bank.add("keep", "Verify the total.", tags=("money",))
    bank.add("bad", "Guess the total.")
    for _ in range(5):
        bank.observe("keep", success=True)
        bank.observe("bad", success=False)
    return bank


@pytest.mark.parametrize("verb", ["report", "audit", "search"])
def test_a_directory_store_is_refused_by_every_verb(tmp_path, capsys, verb):
    store = tmp_path / "bank-dir"
    store.mkdir()
    args = ["skills", verb, "--store", str(store)]
    if verb == "search":
        args += ["--query", "total"]
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1 and lines[0].startswith("error: ")
    assert "cannot read skill bank" in lines[0]
    assert "not a regular file" in lines[0]
    assert captured.out == ""
    assert sorted(p.name for p in store.iterdir()) == []


def test_json_refusal_is_one_object_with_no_stderr(tmp_path, capsys):
    store = tmp_path / "bank-dir"
    store.mkdir()
    assert cli.main(["skills", "report", "--store", str(store), "--json"]) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert "not a regular file" in payload["error"]
    assert captured.err == ""


def test_a_character_device_behind_a_link_is_refused_on_load(tmp_path):
    store = str(tmp_path / "bank-link")
    os.symlink("/dev/null", store)
    with pytest.raises(SkillBankError, match="not a regular file"):
        SkillBank(store)


def test_a_link_to_a_directory_is_refused_on_load(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    store = tmp_path / "link.json"
    os.symlink(target, store)
    with pytest.raises(SkillBankError, match="not a regular file"):
        SkillBank(str(store))


def test_a_link_to_a_file_still_reads_but_never_writes(tmp_path, capsys):
    target = tmp_path / "real.json"
    _bank(target)
    store = tmp_path / "store-link.json"
    os.symlink(target, store)
    before = target.read_bytes()

    assert cli.main(["skills", "report", "--store", str(store)]) == 0
    assert "skills: 2" in capsys.readouterr().out

    assert cli.main(["skills", "audit", "--store", str(store),
                     "--min-uses", "5"]) == 0
    capsys.readouterr()

    assert cli.main(["skills", "audit", "--store", str(store),
                     "--min-uses", "5", "--apply"]) == 2
    captured = capsys.readouterr()
    assert "cannot write skill bank" in captured.err
    assert "is a symlink" in captured.err
    assert captured.err.count("error:") == 1
    assert captured.out == ""
    assert os.path.islink(store)
    assert os.readlink(store) == str(target)
    assert target.read_bytes() == before


def test_a_link_store_refuses_a_library_write_too(tmp_path):
    target = tmp_path / "real.json"
    fresh = _bank(target)
    store = tmp_path / "store-link.json"
    os.symlink(target, store)
    linked = SkillBank(str(store))
    with pytest.raises(SkillBankError, match="is a symlink"):
        linked.set_status("bad", "quarantined")
    assert os.path.islink(store)
    assert SkillBank(str(target)).get("bad").status == "active"
    assert fresh.get("bad").status == "active"


def test_applied_is_false_when_no_status_changes(tmp_path, capsys):
    store = tmp_path / "bank.json"
    _bank(store)
    args = ["skills", "audit", "--store", str(store), "--min-uses", "5",
            "--min-lift", "-1"]
    assert cli.main(args + ["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is False
    assert all(row["status"] == "active" for row in payload["actions"])

    assert cli.main(args + ["--apply"]) == 0
    out = capsys.readouterr().out
    assert "applied: False" in out


def test_applied_is_true_only_when_a_status_changed(tmp_path, capsys):
    store = tmp_path / "bank.json"
    _bank(store)
    assert cli.main(["skills", "audit", "--store", str(store), "--min-uses", "5",
                     "--min-lift", "-0.4", "--apply", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert {row["skill_id"]: row["status"] for row in payload["actions"]} == {
        "keep": "active", "bad": "quarantined"}
    assert SkillBank(str(store)).get("bad").status == "quarantined"


def test_applied_is_false_without_the_flag(tmp_path, capsys):
    store = tmp_path / "bank.json"
    _bank(store)
    assert cli.main(["skills", "audit", "--store", str(store), "--min-uses", "5",
                     "--min-lift", "-0.6", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False


def test_a_missing_store_is_still_an_empty_bank(tmp_path, capsys):
    store = tmp_path / "absent.json"
    assert cli.main(["skills", "report", "--store", str(store), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["skills"] == 0
    assert not store.exists()


def test_a_regular_store_still_persists(tmp_path):
    store = tmp_path / "bank.json"
    _bank(store)
    assert SkillBank(str(store)).get("keep").successes == 5
