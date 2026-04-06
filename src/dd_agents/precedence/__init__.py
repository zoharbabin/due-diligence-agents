"""Document precedence engine: folder priority, version chains, and scoring."""

from dd_agents.precedence.folder_priority import FolderPriorityClassifier, FolderTier
from dd_agents.precedence.scorer import PrecedenceScorer
from dd_agents.precedence.version_chains import VersionChainBuilder, VersionGroup

__all__ = [
    "FolderPriorityClassifier",
    "FolderTier",
    "PrecedenceScorer",
    "VersionChainBuilder",
    "VersionGroup",
]
