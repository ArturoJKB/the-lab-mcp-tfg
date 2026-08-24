"""Tests for OpenRouter provider adapter."""

from __future__ import annotations

from typing import Any

import pytest

from thelab.agents import AgentMessage, LLMProviderError
from thelab.agents.providers import OpenRouterProvider
from thelab.agents.providers.openai_compat import _HTTPResponse


def _make_provider(transport) -> OpenRouterProvider:
    return OpenRouterProvider(
        api_key="sk-test",
        model="openai/gpt-4o-mini",
        transport=transport,
    )


def test_default_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("THELAB_LLM_API_KEY", "sk-env")
    monkeypatch.setenv("THELAB_LLM_MODEL", "anthropic/claude-3-haiku")
    monkeypatch.setenv("OPENROUTER_SITE_NAME", "test-lab")
    provider = OpenRouterProvider()
    assert provider.base_url == "https://openrouter.ai/api/v1"
    assert provider.api_key == "sk-env"
    assert provider.model == "anthropic/claude-3-haiku"
    assert provider._extra_headers.get("X-Title") == "test-lab"


def test_missing_api_key_fails_fast() -> None:
    with pytest.raises(LLMProviderError) as exc_info:
        OpenRouterProvider(api_key="")
    assert exc_info.value.code == "config"


def test_sends_openrouter_headers_and_endpoint() -> None:
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
    provider.complete([AgentMessage(role="user", content="hello")], [])

    assert calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert calls[0]["headers"]["X-Title"] == "thelab"
    assert calls[0]["payload"]["model"] == "openai/gpt-4o-mini"


def test_custom_site_url_header() -> None:
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

    provider = OpenRouterProvider(
        api_key="sk-test",
        site_url="https://example.com",
        site_name="Example Lab",
        transport=transport,
    )
    provider.complete([AgentMessage(role="user", content="hello")], [])
    assert calls[0]["headers"]["HTTP-Referer"] == "https://example.com"
    assert calls[0]["headers"]["X-Title"] == "Example Lab"


def test_text_turn_response() -> None:
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
