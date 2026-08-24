"""Tests for A3.2 — Ollama native LLM provider adapter."""

from __future__ import annotations

from typing import Any

import pytest

from thelab.agents import AgentMessage, LLMProviderError, ToolCallRequest, ToolSpec
from thelab.agents.providers import OllamaProvider
from thelab.agents.providers.ollama import _HTTPResponse


def _make_provider(transport) -> OllamaProvider:
    return OllamaProvider(
        base_url="http://localhost:11434",
        model="llama3.2:3b",
        transport=transport,
    )


def test_default_config_uses_localhost_and_default_model():
    provider = OllamaProvider()
    assert provider.base_url == "http://localhost:11434"
    assert provider.model == "llama3.2:3b"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")
    provider = OllamaProvider()
    assert provider.base_url == "http://ollama.local:11434"
    assert provider.model == "qwen3:4b"


def test_trailing_slash_removed_from_base_url():
    provider = OllamaProvider(base_url="http://localhost:11434/")
    assert provider.base_url == "http://localhost:11434"


def test_request_body_maps_messages_tools_and_json_format():
    calls: list[dict[str, Any]] = []

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        calls.append({"url": url, "headers": headers, "payload": payload})
        return _HTTPResponse(
            status_code=200,
            json_data={
                "model": "llama3.2:3b",
                "message": {"role": "assistant", "content": "{\"answer\": 42}"},
                "done": True,
            },
        )

    provider = _make_provider(transport)
    messages = [
        AgentMessage(role="system", content="sys"),
        AgentMessage(role="user", content="hello"),
    ]
    tools = [
        ToolSpec(name="list_models", description="List models", input_schema={"type": "object"})
    ]
    provider.complete(messages, tools)

    assert calls[0]["url"] == "http://localhost:11434/api/chat"
    assert "Authorization" not in calls[0]["headers"]
    payload = calls[0]["payload"]
    assert payload["model"] == "llama3.2:3b"
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "list_models",
                "description": "List models",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_text_turn_response():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(
            status_code=200,
            json_data={
                "model": "llama3.2:3b",
                "message": {"role": "assistant", "content": "The answer is 42."},
                "done": True,
            },
        )

    provider = _make_provider(transport)
    turn = provider.complete([AgentMessage(role="user", content="?")], [])
    assert turn.text == "The answer is 42."
    assert turn.tool_calls == []


def test_tool_call_turn_response():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(
            status_code=200,
            json_data={
                "model": "llama3.2:3b",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "list_models",
                                "arguments": {"limit": 10},
                            }
                        }
                    ],
                },
                "done": True,
            },
        )

    provider = _make_provider(transport)
    turn = provider.complete([AgentMessage(role="user", content="?")], [])
    assert turn.text is None
    assert turn.tool_calls == [ToolCallRequest(tool="list_models", arguments={"limit": 10}, id=None)]


def test_tool_call_arguments_as_json_string():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(
            status_code=200,
            json_data={
                "model": "llama3.2:3b",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "list_models",
                                "arguments": '{"limit": 10}',
                            }
                        }
                    ],
                },
                "done": True,
            },
        )

    provider = _make_provider(transport)
    turn = provider.complete([AgentMessage(role="user", content="?")], [])
    assert turn.tool_calls == [ToolCallRequest(tool="list_models", arguments={"limit": 10}, id=None)]


def test_empty_content_raises():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(
            status_code=200,
            json_data={
                "model": "llama3.2:3b",
                "message": {"role": "assistant", "content": ""},
                "done": True,
            },
        )

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([AgentMessage(role="user", content="?")], [])
    assert exc_info.value.code == "protocol"


def test_missing_message_raises():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(status_code=200, json_data={"done": True})

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([AgentMessage(role="user", content="?")], [])
    assert exc_info.value.code == "protocol"


def test_client_error_raises():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(status_code=404, text="model not found")

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([AgentMessage(role="user", content="?")], [])
    assert exc_info.value.code == "protocol"
    assert "model not found" in exc_info.value.message


def test_server_error_retries_and_raises():
    attempts = {"count": 0}

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        attempts["count"] += 1
        return _HTTPResponse(status_code=500, text="server error")

    provider = _make_provider(transport)
    provider.max_retries = 2
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([AgentMessage(role="user", content="?")], [])
    assert exc_info.value.code == "server"
    assert attempts["count"] == 3


def test_network_error_raises_with_code():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        raise LLMProviderError("connection refused", code="network")

    provider = _make_provider(transport)
    provider.max_retries = 0
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([AgentMessage(role="user", content="?")], [])
    assert exc_info.value.code == "network"
