"""The supported embedding surface: a small, versioned import contract.

The package exports hundreds of names from research modules that are explicitly
unstable, so an integrator that embeds the engine has no small surface to pin.
This module is that surface: every name below is part of the promise described
in ``docs/main-path.md`` ("The embedding facade") -- additive within
:data:`API_VERSION`, removals only on a version bump, and anything not listed
here is not covered.

It is a re-export, not an implementation: :func:`evolve`, the artifact
strategies, the policies, the durable run store and the loop kernel keep their
canonical modules and their docstrings. Import from here when you want a pin;
import from the canonical module when you are extending the package itself.

    from agentdescent.facade import API_VERSION, evolve, EvolutionResult

    result = evolve(tasks, reward, agent, SingleSlot(initial_value=""))
"""

from __future__ import annotations

from .agents import Usage, claude, cli_agent, openai_compatible
from .async_evolve import async_evolve
from .defaults import DefaultAcceptance, DefaultConflict, DefaultFusion
from .durable_runs import SqliteRunStore
from .evolution import EvolutionResult, EvolvingArtifact, Task, evolve
from .filetree import TreeSpec
from .ledger import Ledger
from .loop_kernel import LoopConfig, LoopKernel, LoopObservation, LoopReport
from .policies import AcceptancePolicy, Policies
from .sampling import TaskSampler
from .selection import SelectionPolicy
from .strategies import AppendRules, KeyedRules, SingleSlot
from .treestrategy import FileTree
from .verifier import ThreeLayerVerifier

#: The facade's own major version. It changes only for a deliberate breaking
#: change to the list below; a new symbol is additive and does not bump it.
API_VERSION = "1"

__all__ = [
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
]
