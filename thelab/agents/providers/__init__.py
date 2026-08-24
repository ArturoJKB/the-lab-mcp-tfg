"""Concrete LLM provider adapters for the agent harness."""

from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider
from .openrouter import OpenRouterProvider

__all__ = ["OllamaProvider", "OpenAICompatProvider", "OpenRouterProvider"]
