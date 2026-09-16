"""Claude backend — the quality option."""

from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel

from bot.config import settings
from bot.services.backends.base import Usage

logger = logging.getLogger(__name__)


class AnthropicBackend:
    name = "anthropic"

    def __init__(self) -> None:
        if settings.anthropic_api_key is None:
            raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        self.client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )

    async def complete(
        self, *, system: str, messages: list[dict], max_tokens: int
    ) -> tuple[str, Usage]:
        response = await self.client.messages.create(
            model=settings.tutor_model,
            max_tokens=max_tokens,
            system=system,
            # A chat turn is not reasoning work; low effort keeps it fast and cheap.
            output_config={"effort": "low"},
            messages=messages,
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        return text.strip(), Usage(
            input_tokens=response.usage.input_tokens or 0,
            output_tokens=response.usage.output_tokens or 0,
        )

    async def complete_json(
        self, *, system: str, prompt: str, schema: type[BaseModel], max_tokens: int
    ) -> tuple[BaseModel | None, Usage]:
        try:
            response = await self.client.messages.parse(
                model=settings.assessor_model,
                max_tokens=max_tokens,
                system=system,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except anthropic.APIError:
            logger.exception("anthropic structured call failed")
            return None, Usage()

        return response.parsed_output, Usage(
            input_tokens=response.usage.input_tokens or 0,
            output_tokens=response.usage.output_tokens or 0,
        )
