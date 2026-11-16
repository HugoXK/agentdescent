"""A run may claim a replay only for the inputs it actually captured.

Two runs can share a ``RunManifest`` and still diverge: the RNG state, the
harness's hidden state and the environment are not manifest inputs. A replay or
counterfactual claim made from such a record overstates what is reconstructible,
and a "same run" comparison can silently change the environment underneath the
score. These tests pin the contract that closes that gap:

* the environment fingerprint stores the allowlisted *names* that were present
  and their count -- never a value, hashed or not -- refuses a secret-shaped
  name even when a caller asks for it, and lets no caller widen the allowlist;
* an RNG boundary digest needs a seed or a state summary -- no guessing;
* a record with an uncaptured source is not eligible, and says what it missed;
* a manifest without a capture is ``replay_eligible=False`` with a reason and
  round-trips through JSON, while the capture never changes ``manifest_id``;
* a trajectory keeps the capture through the store, and ``replay_check`` refuses
  a comparison over a side that was not captured;
* ``ReplayLab`` refuses a counterfactual over an ineligible manifest, names what
  was not reconstructed, and leaves ``baseline`` (not a claim) working.
"""

import hashlib
import json
import re

import pytest

from agentdescent import (EnvironmentFingerprint, ReplayCheck, ReplayFidelity,
                          ReplayNotEligible, RngRecord, RunManifest,
                          build_manifest, content_digest, diff_manifest,
                          replay_check, rng_digest)
from agentdescent.counterfactual import (Intervention, ReplayLab, ReplayTrace,
                                         TraceStep)
from agentdescent.evolvespec import EvolveSpec
from agentdescent.trajectory import Trajectory, TrajectoryStore


def _spec(tmp_path, *, prompt="q"):
    data = tmp_path / "cases.jsonl"
    data.write_text(json.dumps({"prompt": prompt, "gold": "a"}) + "\n")
    return EvolveSpec(kind="text", target=str(tmp_path / "prompt.txt"),
                      data={"path": str(data)}, agent="echo"), data


def _fingerprint(**env):
    values = {"PYTHONHASHSEED": "0", "LANG": "C.UTF-8"}
    values.update(env)
    return EnvironmentFingerprint.capture(
        cwd="/work", tools={"pytest": "9.2.0"}, env=values,
        platform_string="Linux-test", python="3.10.12")


def _fidelity(**env):
    return ReplayFidelity.capture(
        environment=_fingerprint(**env),
        rng=(RngRecord("start", rng_digest(seed="7")),
             RngRecord("interaction:1", rng_digest(seed="7", state={"calls": 1}))),
        hidden_state={"tool:sqlite": {"cursor": 3}})


def _sum(steps):
    return sum(step.payload for step in steps if not step.metadata.get("disabled"))


def _trace(*weights, trace_id="t"):
    return ReplayTrace(trace_id, tuple(
        TraceStep(f"s{i}", payload=weight) for i, weight in enumerate(weights)))


# -- the capture itself ------------------------------------------------------


def test_the_environment_is_recorded_as_names_and_a_count_only():
    fingerprint = _fingerprint()
    assert fingerprint.env_names == ("LANG", "PYTHONHASHSEED")
    assert fingerprint.env_count == 2
    # No value material anywhere in the serialized fingerprint: no 64-hex
    # digest of a value (the old shape) and no literal value either.
    dumped = json.dumps(fingerprint.to_dict(), sort_keys=True)
    assert "C.UTF-8" not in dumped
    assert not re.search(r"[0-9a-f]{64}", dumped)


def test_a_value_change_is_no_longer_detected_only_a_name_change_is():
    """The accepted tradeoff (#952): the fingerprint is names + count.

    A value change cannot be detected without recording value material, so it
    is not detected. A name appearing or disappearing still is.
    """
    one = _fingerprint()
    assert EnvironmentFingerprint.capture(
        cwd="/work", tools={"pytest": "9.2.0"},
        env={"PYTHONHASHSEED": "0", "LANG": "C.UTF-8"},
        platform_string="Linux-test", python="3.10.12") == one
    assert _fingerprint(PYTHONHASHSEED="1").diff(one) == ()
    moved = _fingerprint(TZ="UTC")
    assert "environment:env:TZ" in moved.diff(one)
    assert "environment:env_count" in moved.diff(one)


def test_a_secret_value_can_never_appear_in_any_replay_artifact(tmp_path):
    """The sentinel is an **allowlisted** name, so nothing refuses it by name.

    Today's older test planted the token under a *refused* name and would pass
    even with the value leaking through a different path. Here `LANG` is on the
    allowlist and present: the only reason the sentinel can be absent is that no
    writer keeps value material.
    """
    token = "sk-live-939-do-not-store"
    env = {"PYTHONHASHSEED": "0", "LANG": token}
    fingerprint = EnvironmentFingerprint.capture(
        cwd="/work", tools={}, env=env,
        platform_string="Linux-test", python="3.10.12")
    assert fingerprint.env_names == ("LANG", "PYTHONHASHSEED")
    assert token not in json.dumps(fingerprint.to_dict(), sort_keys=True)

    # Not allowlisted -> dropped; and a caller passing it explicitly cannot
    # widen the allowlist either.
    widened = EnvironmentFingerprint.capture(
        cwd="/work", tools={}, env={**env, "SESSION": token},
        env_names=("SESSION", "LANG", "PYTHONHASHSEED"),
        platform_string="Linux-test", python="3.10.12")
    assert "SESSION" not in widened.env_names
    assert widened.env_names == ("LANG", "PYTHONHASHSEED")

    # A tool version string is caller-supplied text and the fingerprint keeps it
    # verbatim; the manifest's redaction is the layer that removes a credential
    # from it, so plant the token there and assert over the writers below.
    tool_fingerprint = EnvironmentFingerprint.capture(
        cwd="/work", tools={"api_key": token}, env=env,
        platform_string="Linux-test", python="3.10.12")
    spec, data = _spec(tmp_path)
    replay = ReplayFidelity.capture(
        environment=tool_fingerprint,
        rng=(RngRecord("start", rng_digest(seed="0")),))
    manifest = build_manifest(
        spec, data_paths=[str(data)], code_version="1",
        model_config={"model": "m", "api_key": token},
        replay=replay)
    trajectory = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                            rendered="r", output="ok", reward=1.0, replay=replay)
    # Every writer the replay path goes through, named from the code:
    # RunManifest.to_dict(), the record it embeds, Trajectory.to_dict(), and
    # TrajectoryStore's on-disk JSON (it dumps `payload.to_dict()`).
    artifacts = [json.dumps(manifest.to_dict(), sort_keys=True),
                 json.dumps(manifest.replay, sort_keys=True),
                 json.dumps(trajectory.to_dict(), sort_keys=True)]
    store = TrajectoryStore(str(tmp_path / "traj"))
    assert store.record(trajectory)
    written = "".join(p.read_text(encoding="utf-8")
                      for p in (tmp_path / "traj").rglob("*") if p.is_file())
    artifacts.append(written)
    # The digest half is the one that fails at 3f2afa06: the value was stored as
    # a sha256, so a literal-only assertion would pass while the leak stood.
    sentinel_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    for text in artifacts:
        assert token not in text
        # The specific leak Security demonstrated: a sha256 of the value is a
        # recoverable confirmation oracle even after the value is removed.
        assert sentinel_digest not in text
        # And no fingerprint-shaped digest of *any* environment value: the
        # replay record must not carry an `env_hashes` map at all.
        record = json.loads(text)
        replay = record.get("replay") or {}
        env = replay.get("environment") or {}
        assert "env_hashes" not in env


def test_an_rng_boundary_needs_a_seed_or_a_state_summary():
    with pytest.raises(ValueError, match="seed or a state"):
        rng_digest()
    assert rng_digest(seed="7") == rng_digest(seed="7")
    assert rng_digest(seed="7") != rng_digest(seed="8")
    assert rng_digest(state={"counter": 3}) != rng_digest(state={"counter": 4})
    with pytest.raises(ValueError, match="digest"):
        RngRecord("start", "not-a-digest")
    with pytest.raises(ValueError, match="boundary"):
        RngRecord("", rng_digest(seed="1"))


def test_an_uncaptured_source_makes_the_record_ineligible_and_is_named():
    fidelity = ReplayFidelity.capture(
        environment=_fingerprint(),
        rng=(RngRecord("start", rng_digest(seed="0")),),
        hidden_state={"tool:sqlite": {"cursor": 3}},
        uncaptured=("hidden state: the provider's sampler exposes nothing",))
    assert fidelity.eligible is False
    assert "sampler exposes nothing" in " ".join(fidelity.notes())
    assert ReplayFidelity.from_dict(
        json.loads(json.dumps(fidelity.to_dict()))) == fidelity


def test_a_complete_capture_is_eligible_and_round_trips():
    fidelity = _fidelity()
    assert fidelity.eligible is True
    assert fidelity.notes() == ()
    assert ReplayFidelity.from_dict(
        json.loads(json.dumps(fidelity.to_dict()))) == fidelity
    # Hidden-state summaries are digested on the way in, never stored raw.
    assert fidelity.hidden_state["tool:sqlite"] == content_digest({"cursor": 3})


# -- the manifest ------------------------------------------------------------


def test_a_manifest_without_a_capture_is_not_eligible_and_says_why(tmp_path):
    spec, data = _spec(tmp_path)
    manifest = build_manifest(spec, data_paths=[str(data)], code_version="1")
    assert manifest.replay_eligible is False
    assert manifest.replay_notes
    assert "not captured" in " ".join(manifest.replay_notes)
    back = RunManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
    assert back == manifest and back.replay_eligible is False


def test_a_captured_manifest_is_eligible_and_round_trips(tmp_path):
    spec, data = _spec(tmp_path)
    manifest = build_manifest(spec, data_paths=[str(data)], code_version="1",
                              replay=_fidelity())
    assert manifest.replay_eligible is True and manifest.replay_notes == ()
    assert manifest.replay["environment"]["cwd"] == "/work"
    back = RunManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
    assert back == manifest and back.replay_eligible is True


def test_the_capture_does_not_change_the_manifest_id_or_the_input_diff(tmp_path):
    spec, data = _spec(tmp_path)
    plain = build_manifest(spec, data_paths=[str(data)], code_version="1")
    captured = build_manifest(spec, data_paths=[str(data)], code_version="1",
                              replay=_fidelity())
    # The id describes the inputs that make two runs the same run; fidelity is a
    # property of the record kept about one of them.
    assert plain.manifest_id == captured.manifest_id
    assert diff_manifest(plain, captured) == {}


# -- the trajectory ----------------------------------------------------------


def test_a_trajectory_keeps_the_capture_through_the_store(tmp_path):
    store = TrajectoryStore(str(tmp_path))
    captured = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                          rendered="r", replay=_fidelity())
    trace_id = store.record(captured)
    back = store.get(trace_id)
    assert back.replay == captured.replay
    assert back.replay_eligible is True and back.replay_notes == ()
    plain = Trajectory(artifact_id="b", task_id="t", env_fingerprint="env",
                       rendered="r2")
    assert plain.replay_eligible is False and plain.replay_notes


# -- the counterfactual gate -------------------------------------------------


def test_a_counterfactual_is_refused_when_the_manifest_is_not_replay_eligible(tmp_path):
    spec, data = _spec(tmp_path)
    lab = ReplayLab(_sum, manifest=build_manifest(
        spec, data_paths=[str(data)], code_version="1"))
    trace = _trace(1.0, 2.0)
    assert lab.replay_eligible is False
    # Scoring what happened is not a counterfactual claim.
    assert lab.baseline(trace) == 3.0
    with pytest.raises(ReplayNotEligible) as refused:
        lab.counterfactual(trace, [Intervention("s0")])
    assert "not reconstructed" in str(refused.value)
    assert "not captured" in str(refused.value)
    with pytest.raises(ReplayNotEligible):
        lab.leave_one_out(trace)
    with pytest.raises(ReplayNotEligible):
        lab.shapley(trace)


def test_leave_one_out_is_refused_even_when_the_trace_has_no_steps(tmp_path):
    """The guard cannot live only inside `counterfactual()` (#952).

    An empty trace never reaches that call, so before the explicit guard this
    returned a report built from a manifest that captured nothing.
    """
    spec, data = _spec(tmp_path)
    lab = ReplayLab(_sum, manifest=build_manifest(
        spec, data_paths=[str(data)], code_version="1"))
    with pytest.raises(ReplayNotEligible) as refused:
        lab.leave_one_out(ReplayTrace("empty", ()))
    assert "not reconstructed" in str(refused.value)


def test_an_eligible_manifest_allows_the_counterfactual(tmp_path):
    spec, data = _spec(tmp_path)
    lab = ReplayLab(_sum, manifest=build_manifest(
        spec, data_paths=[str(data)], code_version="1", replay=_fidelity()))
    result = lab.counterfactual(_trace(1.0, 2.0), [Intervention("s1")])
    assert result.score == 1.0 and result.delta == 2.0


def test_a_lab_without_a_manifest_makes_no_replay_claim():
    lab = ReplayLab(_sum)
    assert lab.replay_eligible is None
    assert lab.counterfactual(_trace(1.0, 2.0),
                              [Intervention("s1")]).delta == 2.0


# -- comparing a replay ------------------------------------------------------


def test_replay_check_accepts_the_same_run_and_names_a_changed_environment():
    captured = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                          rendered="r", output="ok", reward=1.0, replay=_fidelity())
    same = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                      rendered="r", output="ok", reward=1.0, replay=_fidelity())
    assert replay_check(captured, same) == ReplayCheck(ok=True)
    moved = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                       rendered="r", output="ok", reward=1.0,
                       replay=_fidelity(TZ="UTC"))
    report = replay_check(captured, moved)
    assert report.ok is False
    assert "environment:env:TZ" in report.changed


def test_replay_check_reports_a_changed_verdict():
    captured = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                          rendered="r", output="ok", reward=1.0, replay=_fidelity())
    degraded = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                          rendered="r", output="bad", reward=0.0, replay=_fidelity())
    report = replay_check(captured, degraded)
    assert report.ok is False and report.verdict_changed is True


def test_replay_check_refuses_a_side_that_was_never_captured():
    plain = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                       rendered="r")
    report = replay_check(plain, plain)
    assert report.ok is False
    assert report.notes and "not captured" in " ".join(report.notes)
