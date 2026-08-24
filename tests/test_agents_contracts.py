"""Tests for L1 agent contracts and mock provider."""

from __future__ import annotations

import pytest

from thelab.agents import (
    AgentMessage,
    AgentTurn,
    EchoProvider,
    MockProvider,
    ToolCallRequest,
    ToolSpec,
)


def test_agent_message_defaults():
    msg = AgentMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.tool_call_id is None


def test_tool_spec_round_trip():
    spec = ToolSpec(
        name="list_models",
        description="List approved models",
        input_schema={"type": "object", "properties": {}},
    )
    data = spec.model_dump()
    assert data["name"] == "list_models"


def test_agent_turn_text():
    turn = AgentTurn(text="hello")
    assert turn.text == "hello"
    assert turn.tool_calls == []


def test_agent_turn_tool_calls():
    turn = AgentTurn(
        tool_calls=[ToolCallRequest(tool="list_models", arguments={})]
    )
    assert turn.text is None
    assert len(turn.tool_calls) == 1


def test_agent_turn_rejects_both():
    with pytest.raises(ValueError):
        AgentTurn(text="hello", tool_calls=[ToolCallRequest(tool="list_models")])


def test_agent_turn_rejects_neither():
    with pytest.raises(ValueError):
        AgentTurn(text="", tool_calls=[])


def test_mock_provider_text_turn():
    provider = MockProvider(["answer"])
    turn = provider.complete([], [])
    assert turn.text == "answer"


def test_mock_provider_tool_turn():
    provider = MockProvider([{"tool_calls": [{"tool": "list_models", "arguments": {}}]}])
    turn = provider.complete([], [])
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].tool == "list_models"


def test_mock_provider_exhausted():
    provider = MockProvider([])
    turn = provider.complete([], [])
    assert turn.text == "No further scripted response."


def test_echo_provider_uses_user_message():
    provider = EchoProvider()
    turn = provider.complete(
        [AgentMessage(role="user", content="what runs exist?")], []
    )
    assert turn.text == "what runs exist?"
