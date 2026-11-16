"""#1011: the skill_library "what it learned" line stays one readable line."""

import io
import json
from contextlib import redirect_stdout

from agentdescent import cli, demo

_NEW_SKILL = (
    "---\nname: column-amount\ndescription: Use when totalling.\n---\n\n"
    "# column-amount\n\nTotal the `amount` column.\n\n"
    "- COLUMN: amount\n- `id` is a row number.\n- Reply with only the number.\n"
)


def _seeded(**rules):
    state = {
        "csv-total/references/rules.md": "COLUMN: id\n",
        "date-parse/references/rules.md": "FIELD: month\n",
    }
    for name, value in rules.items():
        state[f"{name}/references/rules.md"] = value
    return state


def test_new_skill_is_named_by_its_bullets_not_its_file():
    state = _seeded()
    state["column-amount/SKILL.md"] = _NEW_SKILL
    line = demo.learned_summary(state, kind="skill_library")
    assert line == (
        "column-amount/SKILL.md (new) -> "
        "'COLUMN: amount | `id` is a row number. (+1 more)'"
    ), line
    assert "\\n" not in line and "---" not in line


def test_unchanged_seed_rules_are_not_reported_as_learned():
    state = _seeded(**{"date-parse": "FIELD: year\n"})
    state["column-amount/SKILL.md"] = _NEW_SKILL
    line = demo.learned_summary(state, kind="skill_library")
    assert "COLUMN: id" not in line and "csv-total/rules.md" not in line
    assert "date-parse/rules.md -> 'FIELD: year'" in line


def test_edited_seeds_keep_todays_line():
    state = _seeded(**{"csv-total": "COLUMN: amount\n", "date-parse": "FIELD: year\n"})
    line = demo.learned_summary(state, kind="skill_library")
    assert line == "csv-total/rules.md -> 'COLUMN: amount'; date-parse/rules.md -> 'FIELD: year'"


def test_nothing_changed_still_names_the_seeds():
    line = demo.learned_summary(_seeded(), kind="skill_library")
    assert line == "csv-total/rules.md -> 'COLUMN: id'; date-parse/rules.md -> 'FIELD: month'"


def test_evoskill_demo_json_learned_is_one_short_line(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                         "--dir", str(tmp_path / "work"),
                         "--algorithm", "evoskill", "--json"])
    assert code == 0, buf.getvalue()
    learned = json.loads(buf.getvalue())["learned"]
    assert "(new) -> 'COLUMN: amount" in learned, learned
    assert "COLUMN: id" not in learned and "FIELD: month" not in learned, learned
    assert "\n" not in learned and "\\n" not in learned, learned
    assert len(learned) < 240, learned
