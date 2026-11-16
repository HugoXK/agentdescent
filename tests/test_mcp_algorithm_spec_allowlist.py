"""MCP ``algorithm_spec`` must obey the operator's write allowlist (#1018).

Every other MCP tool that writes a file routes its destination through
``_check_write`` (``apply``, ``tenant``, ``capability``, ``lineage`` ...), but
``algorithm_spec`` passed ``out`` straight to ``algorithms run``: a host could
name any path on the server's filesystem, including one outside
``AGENTDESCENT_SURFACE_WRITE_DIRS``, and the spec was written there.
"""

import json

from agentdescent.mcp import Tools

_FLAGS = dict(model="deepseek-v4-flash",
              base_url="https://ark.cn-beijing.volces.com/api/coding/v3")


def _prompt_and_cases(tmp_path, n=8):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("be terse\n")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": f"a{i}"}) + "\n" for i in range(n)))
    return prompt, cases


def test_an_out_outside_the_write_allowlist_is_refused(tmp_path):
    prompt, cases = _prompt_and_cases(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside" / "spec.json"

    result = Tools(None, surface_write_dirs=(str(allowed),)).algorithm_spec(
        "rrsi", str(prompt), str(cases), out=str(outside), **_FLAGS)

    assert result["ok"] is False
    assert "write allowlist" in result["error"]
    assert "spec_path" not in result
    assert not outside.exists()


def test_the_default_out_beside_an_outside_target_is_refused_too(tmp_path):
    prompt, cases = _prompt_and_cases(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    result = Tools(None, surface_write_dirs=(str(allowed),)).algorithm_spec(
        "rrsi", str(prompt), str(cases), **_FLAGS)

    assert result["ok"] is False
    assert "write allowlist" in result["error"]
    assert not (tmp_path / "agentdescent.rrsi.spec.json").exists()


def test_an_allowed_out_still_plans(tmp_path):
    prompt, cases = _prompt_and_cases(tmp_path)
    out = tmp_path / "allowed" / "spec.json"

    result = Tools(None, surface_write_dirs=(str(tmp_path),)).algorithm_spec(
        "rrsi", str(prompt), str(cases), out=str(out), **_FLAGS)

    assert result["ok"] is True, result
    assert result["spec_path"] == str(out)
    assert json.loads(out.read_text())["algorithm"] == "rrsi"
