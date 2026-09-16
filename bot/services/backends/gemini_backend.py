"""Google Gemini backend — free, and better at dialogue than the Llama default.

Free tier as of 2026: roughly 1,500 requests/day and 10-15 requests/minute on
the Flash models, with no card required. One conversational turn costs two
requests (partner + assessor), so the daily allowance is on the order of 700
turns.

Note on keys: AI Studio now issues "auth keys" beginning `AQ.` rather than the
older `AIza` standard keys. This backend uses the official SDK, which talks to
the native endpoint — the one place the newer keys work. Routing Gemini through
its OpenAI-compatible shim instead would return 401 for anyone with a current
key, so don't.

Thinking is disabled: a chat turn is not reasoning work, and leaving it on
spends quota and latency on something the learner never sees.
"""

from __future__ import annotations

import logging

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from pydantic import BaseModel

from bot.config import settings
from bot.services.backends.base import Usage

logger = logging.getLogger(__name__)


def _usage(response) -> Usage:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return Usage()
    return Usage(
        input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
        output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
    )


class GeminiBackend:
    name = "gemini"

    def __init__(self) -> None:
        if settings.gemini_api_key is None:
            raise RuntimeError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

    @staticmethod
    def _contents(messages: list[dict]) -> list[types.Content]:
        # Gemini calls the assistant role "model".
        return [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages
        ]

    async def complete(
        self, *, system: str, messages: list[dict], max_tokens: int
    ) -> tuple[str, Usage]:
        response = await self.client.aio.models.generate_content(
            model=settings.gemini_chat_model,
            contents=self._contents(messages),
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                temperature=0.8,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return (response.text or "").strip(), _usage(response)

    async def complete_json(
        self, *, system: str, prompt: str, schema: type[BaseModel], max_tokens: int
    ) -> tuple[BaseModel | None, Usage]:
        try:
            response = await self.client.aio.models.generate_content(
                model=settings.gemini_assessor_model,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=schema,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
        except genai_errors.APIError:
            logger.exception("gemini structured call failed")
            return None, Usage()

        parsed = getattr(response, "parsed", None)
        if parsed is None:
            # The SDK could not validate the response against the schema.
            logger.warning("gemini returned unparseable JSON for %s", schema.__name__)
            return None, _usage(response)
        return parsed, _usage(response)
