"""Ollama native LLM provider adapter implementing the L1 protocol.

Uses Ollama's ``/api/chat`` endpoint with ``format: "json"`` for structured
outputs. No API key is required; configuration is read from environment
variables or constructor arguments.

Privacy boundary: this adapter never logs prompt content. Debug logs contain
only message counts, payload byte sizes, HTTP status codes, and timing.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from thelab.agents.provider import (
    AgentMessage,
    AgentTurn,
    LLMProviderError,
    ToolCallRequest,
    ToolSpec,
)

logger = logging.getLogger(__name__)


class _HTTPResponse:
    """Minimal response object for transport injection in tests."""

    def __init__(
        self,
        status_code: int,
        json_data: dict[str, Any] | None = None,
        text: str = "",
    ):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self) -> Any:
        if self._json is not None:
            return self._json
        return json.loads(self.text)


Transport = Callable[[str, dict[str, str], dict[str, Any]], _HTTPResponse]


class OllamaProvider:
    """LLMProvider adapter for Ollama's native ``/api/chat`` endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 3,
        transport: Transport | None = None,
    ) -> None:
        resolved_base_url = base_url or os.environ.get("OLLAMA_BASE_URL")
        if not resolved_base_url:
            resolved_base_url = "http://localhost:11434"
        self.base_url = resolved_base_url.rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
        self.timeout_seconds = timeout_seconds
        if self.timeout_seconds is None:
            raw_timeout = os.environ.get("OLLAMA_TIMEOUT_SECONDS", "120")
            try:
                self.timeout_seconds = float(raw_timeout)
            except ValueError:
                self.timeout_seconds = 120.0
        self.max_retries = max(0, max_retries)
        self._transport = transport or self._default_transport

    def _default_transport(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> _HTTPResponse:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                return _HTTPResponse(
                    status_code=response.status_code,
                    text=response.text,
                )
        except httpx.TimeoutException as exc:
            raise LLMProviderError(f"request timed out: {exc}", code="network") from exc
        except httpx.NetworkError as exc:
            raise LLMProviderError(f"network error: {exc}", code="network") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"HTTP error: {exc}", code="network") from exc

    @staticmethod
    def _map_messages(messages: list[AgentMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.role == "tool" and msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            out.append(entry)
        return out

    @staticmethod
    def _map_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    def _build_request_body(
        self,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._map_messages(messages),
            "stream": False,
            "format": "json",
        }
        if tools:
            body["tools"] = self._map_tools(tools)
        return body

    def _post_with_retries(self, payload: dict[str, Any]) -> _HTTPResponse:
        url = f"{self.base_url}/api/chat"
        headers = {"Content-Type": "application/json"}

        payload_bytes = len(json.dumps(payload, default=str).encode("utf-8"))
        logger.debug(
            "Ollama request: url=%s messages=%d bytes=%d",
            url,
            len(payload.get("messages", [])),
            payload_bytes,
        )

        last_error: LLMProviderError | None = None
        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            try:
                response = self._transport(url, headers, payload)
            except LLMProviderError as exc:
                last_error = exc
                if exc.code != "network" or attempt == self.max_retries:
                    raise
                delay = 0.5 * (2**attempt)
                logger.debug("Network error, retrying in %.2fs: %s", delay, exc)
                time.sleep(delay)
                continue

            duration = time.perf_counter() - start
            logger.debug(
                "Ollama response: status=%d bytes=%d duration=%.3fs",
                response.status_code,
                len(response.text.encode("utf-8")),
                duration,
            )

            if response.status_code == 429:
                if attempt == self.max_retries:
                    raise LLMProviderError("rate limited", code="rate_limited")
                delay = 0.5 * (2**attempt)
                logger.debug("Rate limited (429), retrying in %.2fs", delay)
                time.sleep(delay)
                continue

            if response.status_code >= 500:
                if attempt == self.max_retries:
                    raise LLMProviderError(
                        f"server error {response.status_code}", code="server"
                    )
                delay = 0.5 * (2**attempt)
                logger.debug("Server error (%d), retrying in %.2fs", response.status_code, delay)
                time.sleep(delay)
                continue

            if response.status_code >= 400:
                raise LLMProviderError(
                    f"client error {response.status_code}: {response.text}", code="protocol"
                )

            return response

        # Should be unreachable, but keeps type checker happy.
        if last_error is not None:
            raise last_error
        raise LLMProviderError("exhausted retries", code="network")

    @staticmethod
    def _parse_tool_calls(message: dict[str, Any]) -> list[ToolCallRequest]:
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise LLMProviderError("tool_calls is not a list", code="protocol")

        requests: list[ToolCallRequest] = []
        for call in raw_calls:
            function = call.get("function") or {}
            name = function.get("name")
            if not name or not isinstance(name, str):
                raise LLMProviderError("tool_call missing function name", code="protocol")
            arguments_raw = function.get("arguments", {})
            if isinstance(arguments_raw, dict):
                arguments = arguments_raw
            else:
                try:
                    arguments = json.loads(arguments_raw)
                except json.JSONDecodeError as exc:
                    raise LLMProviderError(
                        f"tool_call arguments are not valid JSON: {exc}", code="protocol"
                    ) from exc
            if not isinstance(arguments, dict):
                raise LLMProviderError("tool_call arguments are not a JSON object", code="protocol")
            requests.append(ToolCallRequest(tool=name, arguments=arguments, id=None))
        return requests

    def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> AgentTurn:
        payload = self._build_request_body(messages, tools)
        response = self._post_with_retries(payload)

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMProviderError(f"response is not valid JSON: {exc}", code="protocol") from exc

        message = data.get("message") or {}
        if not isinstance(message, dict):
            raise LLMProviderError("response missing message", code="protocol")

        content = message.get("content") or ""
        tool_calls = self._parse_tool_calls(message) if message.get("tool_calls") else []

        usage = {
            "provider": "ollama",
            "model": data.get("model"),
            "prompt_tokens": data.get("prompt_eval_count"),
            "completion_tokens": data.get("eval_count"),
        }

        if tool_calls:
            return AgentTurn(tool_calls=tool_calls, usage=usage)

        if content == "":
            raise LLMProviderError("empty text turn", code="protocol")

        return AgentTurn(text=content, usage=usage)


__all__ = ["OllamaProvider", "_HTTPResponse"]
