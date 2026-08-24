"""Agent harness and provider protocol for The Lab."""

from .global_agents import DiagnosisAgent, Researcher
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
from .providers import OllamaProvider, OpenRouterProvider
from .worker import ExperimentProposal, ProposalStore, WorkerAgent

__all__ = [
    "AgentHarness",
    "AgentMessage",
    "AgentTurn",
    "ApprovalRequiredError",
    "DiagnosisAgent",
    "EchoProvider",
    "ExperimentProposal",
    "GroundingError",
    "LLMProvider",
    "LLMProviderError",
    "MockProvider",
    "OllamaProvider",
    "OpenRouterProvider",
    "ProposalStore",
    "Researcher",
    "ServerConnection",
    "ToolCallRequest",
    "ToolSpec",
    "WorkerAgent",
    "load_script",
]
