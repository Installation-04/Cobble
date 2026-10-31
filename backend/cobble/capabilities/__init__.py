"""Capability interfaces. The core depends on these, never on a product.

The fixed v0.1 pack (packs/v01) provides the implementations.
"""

from .agent import AgentLimits, AgentOutcome, AgentResult, AgentRunner, AgentTask
from .ci import CIProvider, CIState, CIStatus
from .git import GitProvider, MergeRefused, MergeRequestRef, RepoRef
from .llm import ChatResult, LLMClient, Role

__all__ = [
    "AgentLimits",
    "AgentOutcome",
    "AgentResult",
    "AgentRunner",
    "AgentTask",
    "CIProvider",
    "CIState",
    "CIStatus",
    "ChatResult",
    "GitProvider",
    "LLMClient",
    "MergeRefused",
    "MergeRequestRef",
    "RepoRef",
    "Role",
]
