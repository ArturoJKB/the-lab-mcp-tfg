"""LLM provider protocol and typed message contracts for the agent harness."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["system", "user", "assistant", "tool"]


class AgentMessage(BaseModel):
    """A single message in an agent conversation."""

    model_config = ConfigDict(strict=True, extra="forbid")

    role: Role
    content: str = ""
    tool_call_id: str | None = None


class ToolSpec(BaseModel):
    """Description of an MCP tool exposed to a provider."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    """A request from a provider to call a specific tool."""

    model_config = ConfigDict(strict=True, extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class AgentTurn(BaseModel):
    """One provider turn: either text or tool calls, never neither, never both."""

    model_config = ConfigDict(strict=True, extra="forbid")

    text: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    # Optional observability metadata from the provider (model, token counts).
    usage: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> AgentTurn:
        has_text = self.text is not None and self.text != ""
        has_tools = bool(self.tool_calls)
        if has_text and has_tools:
            raise ValueError("turn cannot contain both text and tool_calls")
        if not has_text and not has_tools:
            raise ValueError("turn must contain text or tool_calls")
        return self


class LLMProvider(Protocol):
    """Protocol for pluggable LLM providers used by the harness."""

    def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> AgentTurn: ...


class LLMProviderError(Exception):
    """Provider-level failure with a machine-readable code."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"
