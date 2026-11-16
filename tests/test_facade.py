"""The embedding facade is a pinned contract, not a convenience re-export.

An embedding API is only useful if it cannot change by accident, so this module
pins three things a reader of ``docs/main-path.md`` relies on: the version
string, the exact export list, and the fact that every name resolves to its
canonical module instead of a second copy defined in ``facade``. Changing any
of them is a deliberate edit here, which is the point.
"""

import re

import agentdescent
import agentdescent.facade as facade

#: The pinned surface. A new symbol is additive (append and bump nothing); a
#: removal or a rename is a breaking change and must bump ``API_VERSION``.
PINNED = (
    "API_VERSION",
    "AcceptancePolicy",
    "AppendRules",
    "DefaultAcceptance",
    "DefaultConflict",
    "DefaultFusion",
    "EvolutionResult",
    "EvolvingArtifact",
    "FileTree",
    "KeyedRules",
    "Ledger",
    "LoopConfig",
    "LoopKernel",
    "LoopObservation",
    "LoopReport",
    "Policies",
    "SelectionPolicy",
    "SingleSlot",
    "SqliteRunStore",
    "Task",
    "TaskSampler",
    "ThreeLayerVerifier",
    "TreeSpec",
    "Usage",
    "async_evolve",
    "claude",
    "cli_agent",
    "evolve",
    "openai_compatible",
)


def test_api_version_is_pinned():
    assert facade.API_VERSION == "1"
    assert re.fullmatch(r"\d+", facade.API_VERSION)


def test_the_export_list_is_pinned():
    assert tuple(facade.__all__) == PINNED, (
        "the embedding surface changed: update PINNED deliberately, and bump "
        "API_VERSION if a name was removed or renamed")


def test_the_export_list_is_tidy():
    assert list(facade.__all__) == sorted(set(facade.__all__))
    assert all(not name.startswith("_") for name in facade.__all__)
    assert 20 <= len(facade.__all__) <= 50, "the facade must stay the small surface"


def test_every_symbol_is_the_canonical_object():
    """A facade that redefines a class would drift from the documented one."""
    for name in facade.__all__:
        if name == "API_VERSION":
            continue
        obj = getattr(facade, name)
        home = getattr(obj, "__module__", None)
        assert home and home.startswith("agentdescent."), f"{name} has no home module"
        assert home != "agentdescent.facade", f"{name} is defined in the facade"


def test_the_acceptance_import_works():
    from agentdescent.facade import EvolutionResult, LoopKernel, evolve

    assert callable(evolve)
    assert EvolutionResult is agentdescent.evolution.EvolutionResult
    assert LoopKernel is agentdescent.loop_kernel.LoopKernel


def test_root_visible_names_are_the_same_object():
    for name in facade.__all__:
        if hasattr(agentdescent, name):
            assert getattr(agentdescent, name) is getattr(facade, name), name
