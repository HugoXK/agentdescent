"""`demo --dir` refuses a link planted at a fixture leaf (#1017).

The demo is the one writer that runs before a user has read anything, and it
wrote every fixture and the spec with a plain ``open(..., "w")``. A link named
exactly like a leaf was dereferenced: the demo's bytes landed outside ``--dir``
and the linked file's own bytes were destroyed. ``#1008``/``#977`` settled the
rule for ``init`` and for the tree writer -- ``filetree.dest_problem``, with
``root`` set to the directory the writer was given -- and this file is the same
rule for the demo's two writers, checked before the first byte is written.
"""

import os

import pytest

from agentdescent import cli, demo


def _linked_leaf(root, outside_dir, rel, target_name):
    """Plant ``root/rel`` as a symlink to a real file outside ``root``."""
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside = outside_dir / target_name
    outside.write_text("outside bytes that must survive\n")
    leaf = root / rel
    leaf.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, leaf)
    return leaf, outside


def test_a_symlinked_prompt_leaf_is_refused_before_anything_is_written(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    leaf, outside = _linked_leaf(root, tmp_path / "outside", "prompt.txt",
                                 "keep.txt")

    with pytest.raises(ValueError, match="is a symlink"):
        demo.build(str(root), kind="text")

    assert outside.read_text() == "outside bytes that must survive\n"
    assert leaf.is_symlink()
    # preflight means preflight: the sibling leaves were not written either.
    assert not (root / "cases.jsonl").exists()
    assert not (root / "spec.json").exists()


def test_a_symlinked_spec_leaf_is_refused_before_the_fixtures_are_written(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    leaf, outside = _linked_leaf(root, tmp_path / "outside", "spec.json",
                                 "spec.json")

    with pytest.raises(ValueError, match="is a symlink"):
        demo.build(str(root), kind="text")

    assert outside.read_text() == "outside bytes that must survive\n"
    assert leaf.is_symlink()
    assert not (root / "prompt.txt").exists()


def test_a_symlinked_library_leaf_is_refused_before_the_first_skill_file(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    leaf, outside = _linked_leaf(root, tmp_path / "outside",
                                 os.path.join("csv-total", "references", "rules.md"),
                                 "rules.md")

    with pytest.raises(ValueError, match="is a symlink"):
        demo.build(str(root), kind="skill_library")

    assert outside.read_text() == "outside bytes that must survive\n"
    assert leaf.is_symlink()
    assert not (root / "csv-total" / "SKILL.md").exists()
    assert not (root / "cases.jsonl").exists()


def test_the_cli_reports_the_refusal_and_exits_2(tmp_path, capsys):
    root = tmp_path / "root"
    root.mkdir()
    _, outside = _linked_leaf(root, tmp_path / "outside", "prompt.txt", "keep.txt")

    rc = cli.main(["--store", str(tmp_path / "runs"), "demo", "--dir", str(root),
                   "--kind", "text"])

    err = capsys.readouterr().err
    assert rc == 2
    assert "error: cannot write" in err
    assert "is a symlink" in err
    assert outside.read_text() == "outside bytes that must survive\n"
