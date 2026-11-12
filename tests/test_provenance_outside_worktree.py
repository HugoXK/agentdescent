"""Provenance records must never enter an artifact commit (#966).

``append_provenance`` stores review evidence for a committed lesson: what the
rule was supposed to do, which verifier judged it, which traces and evidence
cards back it. None of that is artifact state, so none of it may appear in the
ledger's commits -- ``Ledger._commit`` stages the whole work tree with
``git add -A`` (ledger.py:495), and a writer that puts files there gets them
swept into whichever commit comes next.

The writer also takes an ``artifact_id`` from its caller and joins it into a
path, so it has to refuse an id that would leave its own directory rather than
write into ``artifacts/`` or anywhere else.
"""

import json
import subprocess
from pathlib import Path

import pytest

from agentdescent.evolution import EvolvingArtifact
from agentdescent.falsification import append_provenance
from agentdescent.ledger import Ledger

RECORD = {
    "rule_id": "d-1",
    "precondition": "base v1; 1 evidence card(s)",
    "behavior_change": ["rule"],
    "expected_effect": {"base": 0.1, "candidate": 0.9},
    "verifier": "falsification-probes:v1",
    "trace_ids": ["t-1"],
    "evidence_card_hash": "abc12345",
}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True,
                          capture_output=True, text=True).stdout


def _ledger(tmp_path):
    def serialize(artifact):
        return {"state": artifact.state, "blast_radius": artifact.blast_radius}

    def deserialize(artifact_id, version, state):
        return EvolvingArtifact(artifact_id, state.get("state", {}), version,
                                state.get("blast_radius", 0.2))

    return Ledger(str(tmp_path / "repo"), serialize, deserialize)


def _committed_files(repo, commit):
    out = _git(repo, "show", "--name-only", "--pretty=format:", commit)
    return [line for line in out.splitlines() if line]


def test_an_artifact_commit_never_carries_provenance(tmp_path):
    """The defect: the next commit after a provenance write swept it in."""
    ledger = _ledger(tmp_path)
    repo = Path(ledger.repo_path)
    ledger.register(EvolvingArtifact("lesson", {"k": "v0"}, blast_radius=0.2))
    base = ledger.head_version(Ledger.DEV)
    ledger.commit(EvolvingArtifact("lesson", {"k": "v1"}, 2, blast_radius=0.2),
                  base, branch=Ledger.DEV)
    first = _git(repo, "rev-parse", "HEAD").strip()

    append_provenance(ledger, "lesson", RECORD)

    # Any later commit is what used to carry the sidecar (and its .lock).
    # `register` commits on both branches, and the bug put the files on the
    # stable commit only -- the following dev checkout then deleted them from
    # the work tree, so checking HEAD alone would miss it.
    ledger.register(EvolvingArtifact("other", {"k": "x"}, blast_radius=0.2))
    second = _git(repo, "rev-parse", "HEAD").strip()
    assert _committed_files(repo, second) == ["artifacts/other.json",
                                              "versions.json"]

    history = _git(repo, "log", "--all", "--name-only",
                   "--pretty=format:").splitlines()
    swept = sorted({name for name in history if name.startswith("provenance/")})
    assert not swept, (
        "no artifact commit may carry the provenance sidecar; found in "
        f"history: {swept}")
    # The commit that already landed is untouched and still reachable.
    assert _git(repo, "rev-parse", first).strip() == first
    assert _committed_files(repo, first) == ["artifacts/lesson.json",
                                             "versions.json"]
    # Nothing was even created in the work tree.
    assert not (repo / "provenance").exists()
    assert (repo / ".git" / "provenance" / "lesson.json").exists()


@pytest.mark.parametrize("bad_id", [
    "../artifacts/lesson",
    "sub/lesson",
    "sub\\lesson",
    "/absolute/lesson",
    "..",
    ".",
])
def test_an_artifact_id_cannot_leave_the_provenance_root(tmp_path, bad_id):
    """`../artifacts/lesson` used to reach the artifact payload itself."""
    ledger = _ledger(tmp_path)
    repo = Path(ledger.repo_path)
    ledger.register(EvolvingArtifact("lesson", {"k": "v0"}, blast_radius=0.2))
    artifact_file = repo / "artifacts" / "lesson.json"
    before = artifact_file.read_bytes()

    with pytest.raises(ValueError, match="single file name"):
        append_provenance(ledger, bad_id, RECORD)

    assert artifact_file.read_bytes() == before
    assert not (repo / ".git" / "provenance").exists(), (
        "a refused id must not create the provenance directory either")
    assert not (tmp_path / "artifacts").exists()


def test_a_second_write_merges_records_instead_of_replacing_them(tmp_path):
    """Existing behaviour from #956: one file per artifact, keyed by rule id."""
    ledger = _ledger(tmp_path)
    ledger.register(EvolvingArtifact("lesson", {"k": "v0"}, blast_radius=0.2))

    first = append_provenance(ledger, "lesson", dict(RECORD, rule_id="d-1"))
    second = append_provenance(ledger, "lesson", dict(RECORD, rule_id="d-2"))

    assert first == second
    assert Path(first).is_relative_to(Path(ledger.repo_path) / ".git")
    data = json.loads(Path(first).read_text(encoding="utf-8"))
    assert sorted(data) == ["d-1", "d-2"]
    assert data["d-1"] == dict(RECORD, rule_id="d-1")
    assert data["d-2"] == dict(RECORD, rule_id="d-2")


def test_appending_provenance_does_not_change_ledger_state(tmp_path):
    """Criterion 4: no CAS change, no HEAD move, no versions.json rewrite."""
    ledger = _ledger(tmp_path)
    repo = Path(ledger.repo_path)
    ledger.register(EvolvingArtifact("lesson", {"k": "v0"}, blast_radius=0.2))
    base = ledger.head_version(Ledger.DEV)
    ledger.commit(EvolvingArtifact("lesson", {"k": "v1"}, 2, blast_radius=0.2),
                  base, branch=Ledger.DEV)

    head = _git(repo, "rev-parse", "HEAD").strip()
    versions = (repo / "versions.json").read_bytes()
    artifact = (repo / "artifacts" / "lesson.json").read_bytes()
    versions_before = dict(ledger.head_version(Ledger.DEV))

    append_provenance(ledger, "lesson", RECORD)

    assert _git(repo, "rev-parse", "HEAD").strip() == head
    assert (repo / "versions.json").read_bytes() == versions
    assert (repo / "artifacts" / "lesson.json").read_bytes() == artifact
    assert dict(ledger.head_version(Ledger.DEV)) == versions_before
