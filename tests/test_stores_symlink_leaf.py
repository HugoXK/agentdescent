"""A store refuses a symlink planted at its own leaf instead of replacing it.

#1008/#1017/#1015 settled this for the tree and fixture writers, and #1029 for
the shared surface helper: a link named exactly like the leaf is refused by
name, never dereferenced, and never silently replaced by a regular file. The
four remaining atomic writers (#1030) did none of that: ``os.replace`` over a
planted link left the outside target alone but destroyed the operator's link.

Each test plants ``<leaf> -> ../outside/keep.json``, runs the real writer, and
reads back the link, its target's bytes and any leftover temporary. A symlinked
*directory* above the leaf stays legal: people keep stores on another disk.
"""

import json
import os
from pathlib import Path

import pytest

from agentdescent import ConsolidationStore, runstore
from agentdescent.evolution import EvolutionResult
from agentdescent.workspace_store import PersistentWorkspaceRegistry
from agentdescent.workspaces import Quota, Workspace


def _result(reward=0.5):
    return EvolutionResult(state={}, rendered="", final_reward=reward,
                           history=[], ledger_log=[])


def _plant_link(leaf, target, payload):
    target.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        target.write_text(payload)
    os.symlink(target, leaf)
    return target.read_bytes()


def _assert_link_kept(leaf, target, before):
    assert os.path.islink(leaf), f"{leaf} is no longer a symlink"
    assert os.readlink(leaf) == str(target)
    assert target.read_bytes() == before


# -- workspace registry ----------------------------------------------------------

def test_workspace_registry_refuses_a_linked_leaf(tmp_path):
    store = tmp_path / "registry.json"
    registry = PersistentWorkspaceRegistry(str(store))
    target = tmp_path / "outside" / "keep.json"
    before = _plant_link(store, target, "keep\n")

    with pytest.raises(ValueError, match="is a symlink"):
        registry.add_workspace(Workspace("t1", "ws", "Research",
                                         Quota(max_tokens=1, max_cost=1.0)))

    _assert_link_kept(store, target, before)
    assert not list(tmp_path.glob(".agentdescent-workspaces-*"))


def test_workspace_registry_still_writes_a_plain_leaf(tmp_path):
    store = tmp_path / "registry.json"
    registry = PersistentWorkspaceRegistry(str(store))
    registry.add_workspace(Workspace("t1", "ws", "Research",
                                     Quota(max_tokens=1, max_cost=1.0)))

    payload = json.loads(store.read_text())
    assert payload["schema_version"] == 1
    assert [w["workspace_id"] for w in payload["workspaces"]] == ["ws"]


# -- consolidation archive -------------------------------------------------------

def test_consolidation_archive_refuses_a_linked_record(tmp_path):
    store = ConsolidationStore(str(tmp_path / "archive"))
    path = store._path("run-a")
    target = tmp_path / "outside" / "keep.json"
    before = _plant_link(path, target, "keep\n")

    with pytest.raises(ValueError, match="is a symlink"):
        store.archive(_result(), run_id="run-a")

    _assert_link_kept(path, target, before)
    assert not list(Path(path).parent.glob("*.tmp"))


def test_mark_exam_refuses_a_linked_record(tmp_path):
    store = ConsolidationStore(str(tmp_path / "archive"))
    store.archive(_result(0.25), run_id="run-b")
    path = store._path("run-b")
    payload = Path(path).read_text()
    target = tmp_path / "outside" / "keep.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload)
    os.remove(path)
    os.symlink(target, path)
    before = target.read_bytes()

    with pytest.raises(ValueError, match="is a symlink"):
        store.mark_exam("run-b", exam="pass", note="x")

    _assert_link_kept(path, target, before)
    assert not list(Path(path).parent.glob("*.tmp"))


def test_a_symlinked_archive_root_stays_legal(tmp_path):
    real = tmp_path / "real-archive"
    real.mkdir()
    alias = tmp_path / "alias"
    os.symlink(real, alias)

    store = ConsolidationStore(str(alias))
    store.archive(_result(), run_id="run-c")

    assert store.find("run-c") is not None
    assert (real / "runs").is_dir()


# -- run store -------------------------------------------------------------------

def test_runstore_write_json_refuses_a_linked_leaf(tmp_path):
    leaf = tmp_path / "run.json"
    target = tmp_path / "outside" / "keep.json"
    before = _plant_link(leaf, target, "keep\n")

    with pytest.raises(runstore.RunStoreError, match="is a symlink"):
        runstore._write_json(str(leaf), {"a": 1})

    _assert_link_kept(leaf, target, before)
    assert not list(tmp_path.glob("*.tmp"))


def test_runstore_write_json_still_writes_a_plain_leaf(tmp_path):
    leaf = tmp_path / "run.json"
    runstore._write_json(str(leaf), {"a": 1})

    assert json.loads(leaf.read_text()) == {"a": 1}
    assert not list(tmp_path.glob("*.tmp"))
