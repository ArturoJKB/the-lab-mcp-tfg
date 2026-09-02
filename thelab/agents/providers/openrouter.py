"""OpenRouter provider adapter.

OpenRouter exposes an OpenAI-compatible chat completions endpoint, but it
recommends sending ``HTTP-Referer`` and ``X-Title`` headers for routing and
rate-limit identification. This adapter is a thin wrapper over
`OpenAICompatProvider` that sets the OpenRouter defaults and those headers.

Configuration is read from environment variables or constructor arguments.
"""

from __future__ import annotations

import os

from .openai_compat import OpenAICompatProvider, Transport


class OpenRouterProvider(OpenAICompatProvider):
    """LLMProvider adapter for OpenRouter's OpenAI-compatible endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 3,
        transport: Transport | None = None,
        site_url: str | None = None,
        site_name: str | None = None,
    ) -> None:
        resolved_base_url = base_url or os.environ.get("THELAB_LLM_BASE_URL")
        if not resolved_base_url:
            resolved_base_url = "https://openrouter.ai/api/v1"
        # An explicitly empty api_key ("") must stay empty: only None defers to env.
        resolved_api_key = (
            api_key
            if api_key is not None
            else (os.environ.get("THELAB_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
        )
        resolved_model = model or os.environ.get("THELAB_LLM_MODEL", "openai/gpt-3.5-turbo")

        extra_headers: dict[str, str] = {}
        referer = site_url or os.environ.get("OPENROUTER_SITE_URL", "")
        title = site_name or os.environ.get("OPENROUTER_SITE_NAME", "thelab")
        if referer:
            extra_headers["HTTP-Referer"] = referer
        if title:
            extra_headers["X-Title"] = title

        super().__init__(
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            model=resolved_model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            extra_headers=extra_headers,
        )


__all__ = ["OpenRouterProvider"]
