"""GitHub publisher: proposal branch, PR, labels and check run, offline."""

import json
import urllib.parse

import pytest

from agentdescent import cli
from agentdescent.github_surface import (
    CheckSpec,
    GitHubConfig,
    GitHubError,
    Proposal,
    github_status,
    load_proposal,
    publish_proposal,
)


class FakeGitHub:
    def __init__(self, *, existing_pull=None, default_branch="main"):
        self.calls = []
        self.refs = {"main": "base123", "develop": "dev123"}
        self.pulls = []
        self.existing_pull = existing_pull
        self.default_branch = default_branch
        self.parents = {}
        self.labels = []
        self.checks = []
        self._n = 0

    def _next(self, prefix):
        self._n += 1
        return f"{prefix}{self._n}"

    def _is_ancestor(self, ancestor, sha):
        seen = set()
        stack = [sha]
        while stack:
            current = stack.pop()
            if current == ancestor:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.parents.get(current, ()))
        return False

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        root = "/repos/o/r"
        assert path.startswith(root), path
        path = path[len(root):]
        if method == "GET" and path == "":
            return {"full_name": "o/r", "default_branch": self.default_branch}
        if method == "GET" and path.startswith("/git/ref/heads"):
            ref = urllib.parse.unquote(path[len("/git/ref/"):])
            branch = ref.split("heads/", 1)[1]
            if branch not in self.refs:
                raise GitHubError("not found", status=404)
            return {"object": {"sha": self.refs[branch]}}
        if method == "GET" and path.startswith("/git/commits/"):
            return {"tree": {"sha": "treebase"}}
        if method == "POST" and path == "/git/blobs":
            return {"sha": self._next("blob")}
        if method == "POST" and path == "/git/trees":
            return {"sha": self._next("tree")}
        if method == "POST" and path == "/git/commits":
            sha = self._next("commit")
            self.parents[sha] = list(payload.get("parents") or ())
            return {"sha": sha}
        if method == "POST" and path == "/git/refs":
            ref = payload["ref"].split("/", 2)[-1]
            if ref in self.refs:
                raise GitHubError("exists", status=422)
            self.refs[ref] = payload["sha"]
            return {"ref": payload["ref"], "object": {"sha": payload["sha"]}}
        if method == "PATCH" and path.startswith("/git/refs/heads"):
            ref = urllib.parse.unquote(path[len("/git/refs/"):])
            branch = ref.split("heads/", 1)[1]
            new_sha = payload["sha"]
            current = self.refs.get(branch)
            if (payload.get("force") is True or current is None
                    or self._is_ancestor(current, new_sha)):
                self.refs[branch] = new_sha
                return {"ref": f"refs/heads/{branch}",
                        "object": {"sha": new_sha}}
            raise GitHubError("Update is not a fast forward", status=422)
        if method == "GET" and path.startswith("/pulls?"):
            return [self.existing_pull] if self.existing_pull else []
        if method == "POST" and path == "/pulls":
            pull = {"number": 7, "html_url": "https://github.com/o/r/pull/7",
                    "title": payload["title"], "state": "open", "draft": payload["draft"],
                    "head": {"sha": self.refs.get(payload["head"].split(":", 1)[1], "")},
                    "base": {"ref": payload["base"]}, "mergeable": True}
            self.pulls.append(pull)
            return pull
        if method == "PATCH" and path == "/pulls/7":
            pull = self.pulls[0]
            pull.update(payload)
            return pull
        if method == "POST" and path == "/issues/7/labels":
            self.labels = list(payload["labels"])
            return []
        if method == "POST" and path == "/check-runs":
            check = {"id": 1, "html_url": "https://github.com/o/r/check/1",
                     "name": payload["name"], "status": "completed",
                     "conclusion": payload["conclusion"]}
            self.checks.append(check)
            return check
        if method == "GET" and path == "/pulls/7":
            return self.pulls[0]
        if method == "GET" and path.startswith("/commits/") and "/check-runs" in path:
            return {"check_runs": self.checks}
        raise AssertionError(f"unexpected call {method} {path}")


def _proposal(**overrides):
    payload = {
        "branch": "agent/skill-csv",
        "title": "feat(skill): improve csv total",
        "body": "The held-out evidence is green.",
        "files": {"skills/csv/SKILL.md": "# CSV\nUse cents."},
        "labels": ["agent-pr", "risk:T2"],
        "run_id": "run-1",
        "artifact_id": "skill-csv",
        "evidence": {"decision": "promote", "artifact_hash": "sha256:abc"},
        "check": CheckSpec(
            conclusion="success", title="evidence", summary="held-out +0.2"),
    }
    payload.update(overrides)
    return Proposal(**payload)


def test_dry_run_makes_no_calls_and_needs_no_token(monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_GITHUB_TOKEN", raising=False)
    fake = FakeGitHub()
    payload = publish_proposal(
        GitHubConfig("o", "r"), _proposal(), dry_run=True, transport=fake)
    assert payload["dry_run"] is True
    assert payload["branch"] == "agent/skill-csv"
    assert payload["files"] == ["skills/csv/SKILL.md"]
    assert fake.calls == []


def test_publish_creates_branch_commit_pr_labels_and_check(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    payload = publish_proposal(
        GitHubConfig("o", "r"), _proposal(), dry_run=False, transport=fake)

    assert payload["dry_run"] is False
    assert payload["pull_request"] == 7
    assert payload["head"].startswith("commit")
    assert payload["check_run"]["name"] == "agentdescent/evidence"
    assert fake.refs["main"] == "base123"
    assert fake.refs["agent/skill-csv"] == payload["head"]
    assert fake.labels == ["agent-pr", "risk:T2"]
    assert fake.checks[0]["conclusion"] == "success"
    encoded = json.dumps(fake.calls)
    assert "secret-token" not in encoded
    assert "sha256:abc" in encoded  # evidence is in the PR body


def test_publish_updates_an_existing_pull(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    existing = {"number": 7, "html_url": "https://github.com/o/r/pull/7",
                "title": "old", "state": "open", "draft": False,
                "head": {"sha": "old"}, "base": {"ref": "main"},
                "mergeable": True}
    fake = FakeGitHub(existing_pull=existing)
    fake.pulls = [existing]
    payload = publish_proposal(
        GitHubConfig("o", "r"), _proposal(), dry_run=False, transport=fake)
    assert payload["pull_request"] == 7
    assert fake.pulls[0]["title"] == "feat(skill): improve csv total"
    assert not any(method == "POST" and path == "/pulls"
                   for method, path, _ in fake.calls)


def test_publish_refuses_base_branch_and_path_traversal(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    with pytest.raises(GitHubError):
        publish_proposal(GitHubConfig("o", "r"),
                         _proposal(branch="main"), dry_run=False,
                         transport=FakeGitHub())
    with pytest.raises(GitHubError):
        _proposal(files={"../escape": "x"})
    with pytest.raises(GitHubError):
        _proposal(files={"/absolute": "x"})


def test_publish_requires_a_token(monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_GITHUB_TOKEN", raising=False)
    with pytest.raises(GitHubError) as error:
        publish_proposal(GitHubConfig("o", "r"), _proposal(), dry_run=False)
    assert "token is not set" in str(error.value)


def test_status_reads_pull_and_checks(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.checks = [{"name": "build", "status": "completed", "conclusion": "success"}]
    payload = github_status(GitHubConfig("o", "r"), 7, transport=fake)
    assert payload["pull_request"] == 7
    assert payload["checks"][0]["conclusion"] == "success"


def test_load_proposal_accepts_a_file_and_list_files(tmp_path):
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps({
        "branch": "agent/x", "title": "t", "body": "",
        "files": [{"path": "a.txt", "content": "hello"}]}), encoding="utf-8")
    proposal = load_proposal(str(path))
    assert proposal.files == {"a.txt": "hello"}


def test_cli_publish_dry_run_and_missing_proposal(tmp_path, capsys):
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps({
        "branch": "agent/x", "title": "t", "body": "",
        "files": {"a.txt": "hello"}}), encoding="utf-8")
    assert cli.main(["github", "publish", "--proposal", str(path),
                     "--owner", "o", "--repo", "r", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True

    assert cli.main(["github", "publish", "--proposal",
                     str(tmp_path / "missing.json"), "--owner", "o",
                     "--repo", "r", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_publish_updates_an_existing_branch_with_an_encoded_ref(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.refs["agent/skill-csv"] = fake.refs["main"]  # fast-forward
    payload = publish_proposal(
        GitHubConfig("o", "r"), _proposal(), dry_run=False, transport=fake)
    update_calls = [call for call in fake.calls
                    if call[0] == "PATCH" and "/git/refs/" in call[1]]
    assert [path for _, path, _ in update_calls] == [
        "/repos/o/r/git/refs/heads%2Fagent%2Fskill-csv"]
    assert all(payload.get("force") is False for _, _, payload in update_calls)
    assert not any(method == "POST" and path == "/git/refs"
                   for method, path, _ in fake.calls)
    assert fake.refs["agent/skill-csv"] == payload["head"]


def test_publish_refuses_a_default_branch_written_as_a_dev_base(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()  # default_branch is "main"
    with pytest.raises(GitHubError, match="repository default branch"):
        publish_proposal(
            GitHubConfig("o", "r"),
            _proposal(base="develop", branch="main"),
            dry_run=False, transport=fake)
    assert [call for call in fake.calls if call[0] != "GET"] == []
    assert "refs/heads%2Fmain" not in json.dumps(fake.calls)


def test_publish_refuses_the_api_default_branch_outside_the_configured_base(
        monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub(default_branch="trunk")
    fake.refs["trunk"] = "trunk-old"
    with pytest.raises(GitHubError, match="repository default branch"):
        publish_proposal(
            GitHubConfig("o", "r"), _proposal(branch="trunk"),
            dry_run=False, transport=fake)
    assert fake.refs["trunk"] == "trunk-old"
    assert [call for call in fake.calls if call[0] != "GET"] == []


def test_publish_refuses_a_non_fast_forward_rewrite(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.refs["agent/skill-csv"] = "old-head"
    with pytest.raises(GitHubError, match="not a fast-forward"):
        publish_proposal(
            GitHubConfig("o", "r"), _proposal(), dry_run=False, transport=fake)
    assert fake.refs["agent/skill-csv"] == "old-head"
    assert not any(method == "POST" and path in ("/git/refs", "/pulls")
                   for method, path, _ in fake.calls)


def test_dry_run_does_not_read_the_repository(monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_GITHUB_TOKEN", raising=False)
    fake = FakeGitHub()
    payload = publish_proposal(
        GitHubConfig("o", "r"),
        _proposal(base="develop", branch="main"),
        dry_run=True, transport=fake)
    assert payload["dry_run"] is True
    assert payload["base"] == "develop"
    assert fake.calls == []
