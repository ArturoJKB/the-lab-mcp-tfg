"""Tests for A1 — OpenAI-compatible LLM provider adapter."""

from __future__ import annotations

import json
from typing import Any

import pytest

from thelab.agents import AgentMessage, LLMProviderError, ToolCallRequest, ToolSpec
from thelab.agents.providers import OpenAICompatProvider
from thelab.agents.providers.openai_compat import _HTTPResponse


def _make_provider(transport) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        model="qwen3:4b",
        transport=transport,
    )


def test_missing_base_url_fails_fast():
    with pytest.raises(LLMProviderError) as exc_info:
        OpenAICompatProvider(base_url="", api_key="x")
    assert exc_info.value.code == "config"
    assert "base_url" in exc_info.value.message.lower()


def test_missing_api_key_fails_fast():
    with pytest.raises(LLMProviderError) as exc_info:
        OpenAICompatProvider(base_url="http://x", api_key="")
    assert exc_info.value.code == "config"
    assert "api_key" in exc_info.value.message.lower()


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("THELAB_LLM_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("THELAB_LLM_API_KEY", "secret")
    monkeypatch.setenv("THELAB_LLM_MODEL", "gpt-4")
    provider = OpenAICompatProvider()
    assert provider.base_url == "http://localhost:9999/v1"
    assert provider.api_key == "secret"
    assert provider.model == "gpt-4"


def test_request_body_maps_messages_and_tools():
    calls: list[dict[str, Any]] = []

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        calls.append({"url": url, "headers": headers, "payload": payload})
        return _HTTPResponse(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                    }
                ]
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

    assert calls[0]["url"] == "http://localhost:11434/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer ollama"
    payload = calls[0]["payload"]
    assert payload["model"] == "qwen3:4b"
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
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "The answer is 42."},
                        "finish_reason": "stop",
                    }
                ]
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
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "list_models",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    provider = _make_provider(transport)
    turn = provider.complete([AgentMessage(role="user", content="list")], [])
    assert turn.text is None
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0] == ToolCallRequest(tool="list_models", arguments={}, id="call_1")


def test_tool_arguments_parsed_from_dict():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {
                                        "name": "get_model_manifest",
                                        "arguments": {"run_id": "run-123"},
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    provider = _make_provider(transport)
    turn = provider.complete([], [])
    assert turn.tool_calls[0].arguments == {"run_id": "run-123"}


def test_malformed_non_json_tool_arguments_raises_protocol():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_3",
                                    "type": "function",
                                    "function": {
                                        "name": "x",
                                        "arguments": "not json",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])
    assert exc_info.value.code == "protocol"


def test_missing_choices_raises_protocol():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(status_code=200, json_data={})

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])
    assert exc_info.value.code == "protocol"


def test_ambiguous_turn_raises_protocol():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                            "tool_calls": [
                                {
                                    "id": "call_4",
                                    "type": "function",
                                    "function": {"name": "x", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])
    assert exc_info.value.code == "protocol"


def test_empty_turn_raises_protocol():
    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return _HTTPResponse(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])
    assert exc_info.value.code == "protocol"


def test_retry_succeeds_after_two_500s():
    responses = [
        _HTTPResponse(status_code=500, text="err"),
        _HTTPResponse(status_code=500, text="err"),
        _HTTPResponse(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
    ]

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return responses.pop(0)

    provider = _make_provider(transport)
    turn = provider.complete([], [])
    assert turn.text == "ok"
    assert len(responses) == 0


def test_retry_exhausted_after_three_500s():
    responses = [
        _HTTPResponse(status_code=500, text="err"),
        _HTTPResponse(status_code=500, text="err"),
        _HTTPResponse(status_code=500, text="err"),
        _HTTPResponse(status_code=500, text="err"),
    ]

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return responses.pop(0)

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])
    assert exc_info.value.code == "server"


def test_400_not_retried():
    calls = []

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        calls.append(payload)
        return _HTTPResponse(status_code=400, text="bad request")

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])
    assert exc_info.value.code == "protocol"
    assert len(calls) == 1


def test_rate_limited_retry_then_success():
    responses = [
        _HTTPResponse(status_code=429, text="slow down"),
        _HTTPResponse(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
    ]

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return responses.pop(0)

    provider = _make_provider(transport)
    turn = provider.complete([], [])
    assert turn.text == "ok"


def test_rate_limited_exhausted_raises_rate_limited():
    responses = [
        _HTTPResponse(status_code=429, text="slow down"),
        _HTTPResponse(status_code=429, text="slow down"),
        _HTTPResponse(status_code=429, text="slow down"),
        _HTTPResponse(status_code=429, text="slow down"),
    ]

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        return responses.pop(0)

    provider = _make_provider(transport)
    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])
    assert exc_info.value.code == "rate_limited"


def test_network_error_retried_then_success():
    responses = [
        LLMProviderError("boom", code="network"),
        _HTTPResponse(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
    ]

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    provider = _make_provider(transport)
    turn = provider.complete([], [])
    assert turn.text == "ok"


def test_golden_tool_call_round_trip():
    """A recorded-style fixture: request shape and response shape match."""
    request_log: list[dict[str, Any]] = []

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _HTTPResponse:
        request_log.append(payload)
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_golden",
                                "type": "function",
                                "function": {
                                    "name": "get_model_manifest",
                                    "arguments": json.dumps({"run_id": "run-20260824-000000-aaaaaaaa"}),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        return _HTTPResponse(status_code=200, json_data=response)

    provider = _make_provider(transport)
    messages = [
        AgentMessage(role="system", content="Grounded assistant."),
        AgentMessage(role="user", content="Fetch manifest for run-20260824-000000-aaaaaaaa."),
    ]
    tools = [
        ToolSpec(
            name="get_model_manifest",
            description="Return the persisted manifest.json for a run.",
            input_schema={
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        )
    ]
    turn = provider.complete(messages, tools)

    assert len(request_log) == 1
    req = request_log[0]
    assert req["model"] == "qwen3:4b"
    assert req["messages"][0]["role"] == "system"
    assert req["messages"][1]["role"] == "user"
    assert req["tools"][0]["type"] == "function"
    assert req["tools"][0]["function"]["name"] == "get_model_manifest"

    assert turn.tool_calls[0].tool == "get_model_manifest"
    assert turn.tool_calls[0].arguments == {"run_id": "run-20260824-000000-aaaaaaaa"}
    assert turn.tool_calls[0].id == "call_golden"
