"""Multiple live heads: Ledger.fork / live_heads / discard_head, PopulationAggregator
multi-head selection, head_for_worker, EvidenceCard.branch, Candidate.branch."""

import tempfile
from agentdescent.evolvable import Diff, EvidenceCard
from agentdescent.evolution import AppendRules, EvolvingArtifact, Task
from agentdescent.ledger import Ledger


def _ledger(tmp_path):
    lg = Ledger(str(tmp_path), lambda a: {"state": dict(a.state)},
                lambda aid, v, s: EvolvingArtifact(aid, s.get("state", {}), v,
                                                   0.2, None, AppendRules()))
    lg.register(EvolvingArtifact("a", {"k": "v0"}, 1, 0.2, None, AppendRules()))
    return lg


def test_fork_creates_independent_branch(tmp_path):
    lg = _ledger(tmp_path)
    assert lg.live_heads() == ["dev"]
    lg.fork("head/0")
    assert lg.live_heads() == ["dev", "head/0"]


def test_commit_to_fork_does_not_touch_dev(tmp_path):
    lg = _ledger(tmp_path)
    lg.fork("head/0")
    snap = lg.snapshot("head/0")
    head = snap.get("a")
    cand = head.apply(Diff(diff_id="d", target="a", ops={"k2": "v2"}, author="w"))
    lg.commit(cand, {"a": snap.version["a"]}, branch="head/0")
    assert lg.head_version("dev").get("a") == 1
    assert lg.head_version("head/0").get("a") == 2


def test_fork_refuses_non_head_names(tmp_path):
    lg = _ledger(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        lg.fork("stable")
    with pytest.raises(ValueError):
        lg.fork("dev")


def test_discard_head(tmp_path):
    lg = _ledger(tmp_path)
    lg.fork("head/0")
    assert "head/0" in lg.live_heads()
    lg.discard_head("head/0")
    assert lg.live_heads() == ["dev"]


def test_discard_head_refuses_non_fork(tmp_path):
    lg = _ledger(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        lg.discard_head("dev")


def test_live_heads_after_multiple_forks(tmp_path):
    lg = _ledger(tmp_path)
    lg.fork("head/0")
    lg.fork("head/1")
    lg.fork("head/2")
    assert lg.live_heads() == ["dev", "head/0", "head/1", "head/2"]


def test_candidate_has_branch_field():
    from agentdescent.selection import Candidate
    c = Candidate(artifact_id="a", version=1)
    assert c.branch is None
    c2 = Candidate(artifact_id="a", version=1, branch="head/0")
    assert c2.branch == "head/0"


def test_evidence_card_has_branch_field():
    card = EvidenceCard(
        diff=Diff(diff_id="d", target="a", ops={"x": "v"}, author="w"),
        base_version={"a": 1}, touched=["a"])
    assert card.branch is None
    card2 = EvidenceCard(
        diff=Diff(diff_id="d", target="a", ops={"x": "v"}, author="w"),
        base_version={"a": 1}, touched=["a"], branch="head/0")
    assert card2.branch == "head/0"


def test_head_for_worker_returns_dev_by_default(tmp_path):
    from agentdescent.aggregator import Aggregator, AggregatorConfig
    from agentdescent.scheduler import AuditScheduler
    from agentdescent.verifier import ThreeLayerVerifier, VerifierBudget
    lg = _ledger(tmp_path)
    v = ThreeLayerVerifier(eval_fn=lambda a, t: 0.5, held_out=[1, 2, 3],
                           budget=VerifierBudget())
    agg = Aggregator(lg, v, AuditScheduler(), AggregatorConfig())
    assert agg.head_for_worker(0) == "dev"
    assert agg.head_for_worker(99) == "dev"


def test_population_head_for_worker_cycles_forks(tmp_path):
    from agentdescent.aggregator import AggregatorConfig
    from agentdescent.scheduler import AuditScheduler
    from agentdescent.verifier import ThreeLayerVerifier, VerifierBudget
    from agentdescent.population import PopulationAggregator
    from agentdescent.selection import SingleHead
    lg = _ledger(tmp_path)
    v = ThreeLayerVerifier(eval_fn=lambda a, t: 0.5, held_out=[1, 2, 3],
                           budget=VerifierBudget())
    agg = PopulationAggregator(lg, v, AuditScheduler(), AggregatorConfig(batch_trigger=1),
                               selection=SingleHead(), artifact_id="a")
    # Before any forks: dev
    assert agg.head_for_worker(0) == "dev"
    # Simulate forks
    agg._forks = ["head/0", "head/1"]
    assert agg.head_for_worker(0) == "dev"      # worker 0 = primary head
    assert agg.head_for_worker(1) == "head/0"
    assert agg.head_for_worker(2) == "head/1"
    assert agg.head_for_worker(3) == "head/0"   # wraps


def test_population_commit_state_to_fork(tmp_path):
    from agentdescent.aggregator import AggregatorConfig
    from agentdescent.scheduler import AuditScheduler
    from agentdescent.verifier import ThreeLayerVerifier, VerifierBudget
    from agentdescent.population import PopulationAggregator
    from agentdescent.selection import SingleHead
    lg = _ledger(tmp_path)
    lg.fork("head/0")
    v = ThreeLayerVerifier(eval_fn=lambda a, t: 0.5, held_out=[1, 2, 3],
                           budget=VerifierBudget())
    agg = PopulationAggregator(lg, v, AuditScheduler(), AggregatorConfig(batch_trigger=1),
                               selection=SingleHead(), artifact_id="a")
    ver = agg._commit_state({"k": "v1", "k3": "v3"}, "test", branch="head/0")
    assert ver is not None
    assert lg.head_version("dev").get("a") == 1
    assert lg.head_version("head/0").get("a") == 2


def test_default_evolve_unchanged(tmp_path):
    """Default path (no population, no audit drain) must be unchanged."""
    from agentdescent.evolution import evolve
    from agentdescent.strategies import AppendRules
    tasks = [Task(id=f"t{i}", prompt=f"p{i}") for i in range(6)]
    r = evolve(tasks, lambda t, o: 0.0,
               run=lambda rd, t: "a", propose=lambda rd, t, o, r: None,
               strategy=AppendRules(),
               max_rollouts=4, n_workers=1, rounds=2)


def test_evidence_buffer_buckets_by_branch():
    """Cards from different branches must land in separate merge buckets."""
    from agentdescent.aggregator import EvidenceBuffer, AggregatorConfig
    base = {"k": "v"}
    d0 = Diff(diff_id="d0", target="a", ops={"k0": "v0"}, author="w0")
    d1 = Diff(diff_id="d1", target="a", ops={"k1": "v1"}, author="w1")
    c0 = EvidenceCard(diff=d0, base_version={"a": 1}, touched=["a"], branch="")
    c1 = EvidenceCard(diff=d1, base_version={"a": 1}, touched=["a"], branch="head/1")
    buf = EvidenceBuffer()
    buf.add(c0)
    buf.add(c1)
    # Two separate buckets, not one merged bucket
    ready = buf.ready(AggregatorConfig(batch_trigger=1))
    assert ("a", "") in ready and ("a", "head/1") in ready
    assert len(ready) == 2, f"expected 2 buckets, got {ready}"


def test_prepare_merges_against_own_branch(tmp_path):
    """A head/1 diff is merged against head/1's version vector, not dev's."""
    from agentdescent.aggregator import Aggregator, AggregatorConfig, _Candidate
    from agentdescent.scheduler import AuditScheduler
    from agentdescent.verifier import ThreeLayerVerifier, VerifierBudget
    lg = _ledger(tmp_path)
    # dev at v1, head/0 at v5
    lg.fork("head/0")
    snap = lg.snapshot("head/0")
    head = snap.get("a")
    for i in range(4):
        cand = head.apply(Diff(diff_id=f"h{i}", target="a", ops={f"k{i}": "v"}, author="w"))
        lg.commit(cand, {"a": snap.version["a"]}, branch="head/0")
        snap = lg.snapshot("head/0")
        head = snap.get("a")
    v = ThreeLayerVerifier(eval_fn=lambda a, t: 0.5, held_out=[1, 2, 3],
                           budget=VerifierBudget())
    agg = Aggregator(lg, v, AuditScheduler(), AggregatorConfig(batch_trigger=1))
    # A card proposed against head/0 at v5
    card = EvidenceCard(
        diff=Diff(diff_id="d", target="a", ops={"new": "v"}, author="w"),
        base_version={"a": 5}, touched=["a"], branch="head/0")
    agg.ingest(card)
    prepared = agg._prepare("a", "head/0")
    assert isinstance(prepared, _Candidate), f"expected candidate, got {prepared}"
    assert prepared.branch == "head/0"
    assert prepared.head["a"] == 5, "must merge against head/0's version, not dev's"
