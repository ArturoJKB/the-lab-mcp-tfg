"""Agent harness and provider protocol for The Lab."""

from .harness import AgentHarness, ApprovalRequiredError, GroundingError, ServerConnection
from .mock import EchoProvider, MockProvider, load_script
from .provider import (
    AgentMessage,
    AgentTurn,
    LLMProvider,
    LLMProviderError,
    ToolCallRequest,
    ToolSpec,
)

__all__ = [
    "AgentHarness",
    "AgentMessage",
    "AgentTurn",
    "ApprovalRequiredError",
    "EchoProvider",
    "GroundingError",
    "LLMProvider",
    "LLMProviderError",
    "MockProvider",
    "ServerConnection",
    "ToolCallRequest",
    "ToolSpec",
    "load_script",
]
