"""`harness check` and the `FileTree` it configures must share one matcher.

`check()` used `fnmatch` while the tree used `filetree.match_any`, so the two
surfaces disagreed on `*` vs `**`, bare directory patterns and overlapping
globs (#932). These tests pin the agreement, not either matcher in isolation.
"""

import pytest

from agentdescent.filetree import match_any
from agentdescent.harness_manifest import (
    HarnessComponent, HarnessManifest, load_manifest,
)
from agentdescent.treestrategy import FileTree


def _manifest(components, **overrides):
    payload = {"schema_version": 1, "components": components}
    payload.update(overrides)
    return load_manifest(payload)


def _component(name, paths, **overrides):
    return {"name": name, "paths": list(paths), **overrides}


def _writable(manifest, path):
    return FileTree({}, **manifest.tree_kwargs()).writable(path)


def test_catch_all_first_does_not_hide_a_later_frozen_component():
    manifest = _manifest([
        _component("all", ["**"]),
        _component("safety", ["safety/**"], frozen=True),
    ])
    report = manifest.check({"safety/rules.md": "x"})
    assert report["ok"] is False
    assert any("safety/rules.md" in row for row in report["violations"])
    assert _writable(manifest, "safety/rules.md") is False


def test_bare_directory_pattern_freezes_its_subtree():
    manifest = _manifest([
        _component("all", ["**"]),
        _component("tests", ["tests"], frozen=True),
    ])
    report = manifest.check({"tests/x.md": "x"})
    assert report["ok"] is False
    assert _writable(manifest, "tests/x.md") is False


def test_single_star_does_not_cross_a_slash_in_allowed_paths():
    manifest = _manifest(
        [_component("src", ["src/**"])], allowed_paths=["src/*.py"])
    report = manifest.check({"src/sub/x.py": "x"})
    assert report["ok"] is False
    assert any("allowed_paths" in row for row in report["violations"])
    # `**` is how you say "any depth", and the two surfaces agree on it.
    admits = _manifest(
        [_component("src", ["src/**"])], allowed_paths=["src/**"])
    assert admits.check({"src/sub/x.py": "x"})["ok"] is True


def test_budgets_are_charged_to_every_matching_component():
    # Catch-all listed first: the later component's budget must still bite.
    catch_all_first = _manifest([
        _component("all", ["**"]),
        _component("docs", ["docs/**"], max_files=2),
    ])
    report = catch_all_first.check(
        {"docs/a.md": "x", "docs/b.md": "x", "docs/c.md": "x"})
    assert report["ok"] is False
    assert any("docs: 3 files > max_files 2" in row
               for row in report["violations"])

    # Same manifest, safety component first: the verdict must not depend on order.
    docs_first = _manifest([
        _component("docs", ["docs/**"], max_lines=2),
        _component("all", ["**"]),
    ])
    report = docs_first.check({"docs/a.md": "x\ny\nz\n"})
    assert report["ok"] is False
    assert any("docs: 3 lines > max_lines 2" in row
               for row in report["violations"])


def test_read_only_beats_editable_for_overlapping_components():
    manifest = _manifest([
        _component("skill", ["skills/pdf/**"]),
        _component("rules", ["skills/pdf/rules.md"], editable=False),
    ])
    report = manifest.check({"skills/pdf/rules.md": "x"})
    assert report["ok"] is False
    assert any("rules.md" in row for row in report["violations"])


@pytest.mark.parametrize("path", [
    "system.md",
    "skills/pdf/SKILL.md",
    "skills/pdf/sub/deep.md",
    "skills/pdf/rules.md",
    "tests/x.md",
    "safety/policy.md",
    "docs/x.md",
])
def test_check_refusal_agrees_with_tree_writability(path):
    """The contract this issue exists to restore: one verdict on both surfaces."""
    manifest = _manifest([
        _component("prompt", ["*.md"]),
        _component("skill", ["skills/**/*.md"]),
        _component("rules", ["skills/pdf/rules.md"], frozen=True),
        _component("tests", ["tests"], editable=False),
        _component("safety", ["safety/**"], frozen=True),
    ])
    refused = not manifest.check({path: "x"})["ok"]
    assert refused is (not _writable(manifest, path))


def test_match_any_is_the_shared_semantics():
    # `*` is one segment, `**` spans segments, a bare directory is its subtree.
    assert match_any("src/sub/x.py", ["src/*.py"]) is False
    assert match_any("src/sub/x.py", ["src/**/*.py"]) is True
    assert match_any("tests/a/b.md", ["tests"]) is True
