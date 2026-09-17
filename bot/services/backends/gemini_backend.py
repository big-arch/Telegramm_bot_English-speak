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

import asyncio
import logging

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from pydantic import BaseModel

from bot.config import settings
from bot.services.backends.base import Usage

logger = logging.getLogger(__name__)

# Google retires models for new projects without retiring them for existing
# ones, so a name that is correct in the documentation, correct in a blog post
# and correct for one account is still 404 for another. Hard-coding one is
# therefore a guess with a shelf life — and when it expires the symptom is "the
# bot can't see my photo", which names no model and points at nothing.
#
# So the configured name is a preference, not a requirement: a 404 sends the
# backend to ask the account what it actually has. Resolved once per process.
_DISCOVERED: dict[str, str] = {}

_NOT_A_CHAT_MODEL = ("embedding", "aqa", "imagen", "veo", "tts", "image-generation")


def _usage(response) -> Usage:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return Usage()
    return Usage(
        input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
        output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
    )


def _is_missing(exc: genai_errors.APIError) -> bool:
    """Whether this error means "that model, not this key"."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = str(exc).lower()
    return code == 404 or "not found" in text or "not available" in text


class GeminiBackend:
    name = "gemini"

    def __init__(self) -> None:
        if settings.gemini_api_key is None:
            raise RuntimeError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

    async def _alternative_to(self, wanted: str) -> str | None:
        """A model this key really has, when the configured one is gone.

        Newest first, because Google's naming sorts that way and the newest
        Flash is the one still being served. Cached: this costs a round-trip,
        and the answer does not change while the process lives.
        """
        if wanted in _DISCOVERED:
            return _DISCOVERED[wanted]

        try:
            models = await asyncio.to_thread(lambda: list(self.client.models.list()))
        except Exception:  # noqa: BLE001 - discovery must never be the failure
            logger.exception("could not list Gemini models")
            return None

        usable = sorted(
            (
                name
                for model in models
                if (name := (model.name or "").removeprefix("models/"))
                and "generateContent" in (getattr(model, "supported_actions", None) or ["generateContent"])
                and not any(word in name for word in _NOT_A_CHAT_MODEL)
            ),
            reverse=True,
        )
        # Flash is free-tier friendly and fast; anything else beats nothing.
        choice = next((m for m in usable if "flash" in m), None) or next(iter(usable), None)
        if choice:
            logger.warning("gemini model %r unavailable; using %r instead", wanted, choice)
            _DISCOVERED[wanted] = choice
        return choice

    async def _generate(self, *, model: str, **kwargs):
        """One call, retried once against a model this key actually has."""
        try:
            return await self.client.aio.models.generate_content(model=model, **kwargs)
        except genai_errors.APIError as exc:
            if not _is_missing(exc):
                raise
            alternative = await self._alternative_to(model)
            if alternative is None or alternative == model:
                raise
            return await self.client.aio.models.generate_content(model=alternative, **kwargs)

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
        response = await self._generate(
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

    async def describe_image(
        self, *, image: bytes, mime: str, prompt: str, max_tokens: int
    ) -> tuple[str, Usage]:
        response = await self._generate(
            model=settings.gemini_chat_model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=image, mime_type=mime),
                        types.Part(text=prompt),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=0.4,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return (response.text or "").strip(), _usage(response)

    async def complete_json(
        self, *, system: str, prompt: str, schema: type[BaseModel], max_tokens: int
    ) -> tuple[BaseModel | None, Usage]:
        try:
            response = await self._generate(
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
