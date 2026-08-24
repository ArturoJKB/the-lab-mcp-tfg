"""Deterministic mock provider for offline harness tests and demos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .provider import AgentMessage, AgentTurn, ToolCallRequest, ToolSpec


class MockProvider:
    """A scripted provider that returns a pre-defined sequence of turns.

    Each entry in *script* is either:
    - a string -> returned as an assistant text turn, or
    - a dict with key ``tool_calls`` -> list of ``{"tool": str, "arguments": dict}``
      -> returned as a tool-call turn.
    """

    def __init__(self, script: list[str | dict[str, Any]]):
        self.script = script
        self._index = 0

    def complete(self, messages: list[AgentMessage], tools: list[ToolSpec]) -> AgentTurn:
        """Return the next scripted turn."""
        if self._index >= len(self.script):
            return AgentTurn(text="No further scripted response.")
        item = self.script[self._index]
        self._index += 1
        if isinstance(item, str):
            return AgentTurn(text=item)
        calls = item.get("tool_calls", [])
        return AgentTurn(
            tool_calls=[
                ToolCallRequest(tool=c["tool"], arguments=c.get("arguments", {}))
                for c in calls
            ]
        )


class EchoProvider:
    """Provider that immediately echoes the user's goal back as the answer."""

    def __init__(self, answer: str = ""):
        self.answer = answer

    def complete(self, messages: list[AgentMessage], tools: list[ToolSpec]) -> AgentTurn:
        if messages:
            user = [m for m in messages if m.role == "user"]
            if user:
                return AgentTurn(text=self.answer or user[-1].content)
        return AgentTurn(text=self.answer or "echo")


def load_script(path: str) -> list[str | dict[str, Any]]:
    """Load a mock-provider script from JSON.

    Accepts either a list of turns or a dict with a ``turns`` key.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        turns = data.get("turns")
        if isinstance(turns, list):
            return turns
    raise ValueError("mock script must be a list of turns or {'turns': [...]}")


__all__ = ["MockProvider", "EchoProvider", "load_script"]
