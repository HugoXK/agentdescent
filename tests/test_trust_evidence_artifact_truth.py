"""An unchanged artifact must not be repriced as learning (#937).

The evidence builder turns paired scores into a promotion bundle. When the
artifact is byte-identical before and after, a moved score is evaluation noise:
reporting its delta as gain is how a run with `accepted=0` and no change on disk
claims an improvement. The bundle therefore has to carry the artifact comparison
and zero the gain on it, and the promotion seam must not promote that bundle.
"""

from agentdescent.promotion import PromotionAction, PromotionRules, promote
from agentdescent.trust_evidence import TrustEvidence, build_trust_evidence


def _scores(gain=0.5, n=40):
    before = {f"t{i}": 0.5 for i in range(n)}
    after = {f"t{i}": 0.5 + gain for i in range(n)}
    return before, after


def _evidence(**kwargs):
    before, after = _scores()
    return build_trust_evidence(
        before, after, contaminated=False, risk=0.1, approved=True, **kwargs)


def test_an_unchanged_artifact_reports_zero_gain_and_noise_only():
    evidence = _evidence(artifact_changed=False)

    assert evidence.artifact_changed is False
    assert evidence.noise_only is True
    assert evidence.gain == 0.0
    assert evidence.eval_result.delta == 0.0
    assert evidence.eval_result.passed is False
    assert evidence.metadata["artifact_changed"] is False
    assert evidence.metadata["noise_only"] is True
    assert "artifact unchanged" in evidence.eval_result.detail


def test_an_unchanged_artifact_cannot_promote():
    unchanged = promote(
        _evidence(artifact_changed=False).to_promotion_request("skill-1"),
        PromotionRules())

    assert unchanged.action != PromotionAction.PROMOTE
    assert unchanged.accepted is False
    assert any("eval gate did not pass" in reason
               for reason in unchanged.reasons)

    # The control: the same scores on a changed artifact do promote, so the
    # artifact comparison — not the scores — is what blocked it.
    changed = promote(
        _evidence(artifact_changed=True).to_promotion_request("skill-1"),
        PromotionRules())
    assert changed.action == PromotionAction.PROMOTE


def test_a_changed_or_unknown_artifact_keeps_the_measured_gain():
    for flag in (True, None):
        evidence = _evidence(artifact_changed=flag)
        assert evidence.artifact_changed is flag
        assert evidence.noise_only is False
        assert evidence.gain == evidence.eval_result.delta
        assert evidence.eval_result.delta > 0
        assert promote(evidence.to_promotion_request("skill-1"),
                       PromotionRules()).action == PromotionAction.PROMOTE


def test_the_artifact_comparison_travels_with_the_evidence():
    unchanged = _evidence(artifact_changed=False).to_dict()
    assert unchanged["artifact_changed"] is False
    assert unchanged["noise_only"] is True

    unknown = _evidence().to_dict()
    assert "artifact_changed" not in unknown
    assert "noise_only" not in unknown

    request = _evidence(artifact_changed=False).to_promotion_request("skill-1")
    assert request.metadata["artifact_changed"] is False
    assert request.metadata["noise_only"] is True
    assert isinstance(request.eval_result, type(_evidence().eval_result))


def test_the_default_bundle_is_the_one_that_existed_before():
    before, after = _scores()
    base = build_trust_evidence(before, after, contaminated=False, risk=0.1)
    evidence = TrustEvidence(
        eval_result=base.eval_result, canary=base.canary,
        contaminated=False, risk=0.1)
    assert evidence.artifact_changed is None
    assert evidence.noise_only is False
    assert evidence.gain == evidence.eval_result.delta
