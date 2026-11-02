"""Capability interfaces. The core depends on these, never on a product.

The catalogue modules (catalog/) provide the implementations.
"""

from .agent import AgentLimits, AgentOutcome, AgentResult, AgentRunner, AgentTask
from .ci import CIProvider, CIState, CIStatus
from .git import GitProvider, MergeRefused, MergeRequestRef, RepoRef, TagExists
from .llm import ChatResult, LLMClient, Role
from .preview import PreviewProvider, PreviewRequest, PreviewState, PreviewStatus

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
    "PreviewProvider",
    "PreviewRequest",
    "PreviewState",
    "PreviewStatus",
    "RepoRef",
    "Role",
    "TagExists",
]
