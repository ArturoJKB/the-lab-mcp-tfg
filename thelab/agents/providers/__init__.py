"""Concrete LLM provider adapters for the agent harness."""

from .openai_compat import OpenAICompatProvider

__all__ = ["OpenAICompatProvider"]
