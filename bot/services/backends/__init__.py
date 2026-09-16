"""Backend selection.

Constructed lazily so that an unset key for a provider you are not using is
never an error — the free stack must not require an Anthropic key to exist.
"""

from __future__ import annotations

from functools import lru_cache

from bot.config import settings
from bot.services.backends.base import LLMBackend, Usage

__all__ = ["get_backend", "LLMBackend", "Usage"]


@lru_cache(maxsize=1)
def get_backend() -> LLMBackend:
    provider = settings.llm_provider.lower()

    if provider == "groq":
        from bot.services.backends.groq_backend import GroqBackend

        return GroqBackend()

    if provider == "gemini":
        from bot.services.backends.gemini_backend import GeminiBackend

        return GeminiBackend()

    if provider == "anthropic":
        from bot.services.backends.anthropic_backend import AnthropicBackend

        return AnthropicBackend()

    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. "
        "Supported: groq (free, works everywhere), gemini (free), anthropic."
    )
