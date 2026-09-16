"""Groq backend — free, and available where Gemini is not.

Groq's free tier covers both speech recognition and chat, so one key runs the
whole bot. That matters practically: Gemini's API is unavailable in a number of
countries (Russia among them), and Groq is not.

Quality is below a frontier model, which is why two safeguards elsewhere carry
more weight here: the assessor's findings are dropped unless the model can
quote the learner verbatim (`llm.assess`), and the correction policy lives in
code rather than in the prompt (`services/feedback.py`).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from bot.config import settings
from bot.services.backends.base import Usage

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _strictify(node: Any) -> Any:
    """Make a JSON Schema acceptable to constrained decoding.

    Strict mode requires every object to forbid extra properties and to list
    every property as required. Pydantic emits neither, so we add them.

    Returns a new structure and never touches the input — pydantic can hand
    back a cached schema object, and quietly editing it would corrupt every
    later use of that model.
    """
    if isinstance(node, dict):
        result = {k: _strictify(v) for k, v in node.items()}
        if node.get("type") == "object" and "properties" in node:
            result["additionalProperties"] = False
            result["required"] = list(node["properties"].keys())
        return result
    if isinstance(node, list):
        return [_strictify(v) for v in node]
    return node


def _usage(response) -> Usage:
    u = getattr(response, "usage", None)
    if u is None:
        return Usage()
    return Usage(
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
    )


class GroqBackend:
    name = "groq"

    def __init__(self) -> None:
        if settings.groq_api_key is None:
            raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is not set")
        self.client = AsyncOpenAI(
            api_key=settings.groq_api_key.get_secret_value(),
            base_url=GROQ_BASE_URL,
        )

    async def complete(
        self, *, system: str, messages: list[dict], max_tokens: int
    ) -> tuple[str, Usage]:
        response = await self.client.chat.completions.create(
            model=settings.groq_chat_model,
            max_tokens=max_tokens,
            temperature=0.8,
            messages=[{"role": "system", "content": system}, *messages],
        )
        text = (response.choices[0].message.content or "").strip()
        return text, _usage(response)

    async def describe_image(
        self, *, image: bytes, mime: str, prompt: str, max_tokens: int
    ) -> tuple[str, Usage]:
        import base64

        from bot.services.backends.base import VisionUnsupported

        if not settings.groq_vision_model:
            raise VisionUnsupported("GROQ_VISION_MODEL is empty")

        data_uri = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        try:
            response = await self.client.chat.completions.create(
                model=settings.groq_vision_model,
                max_tokens=max_tokens,
                temperature=0.4,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }
                ],
            )
        except APIError as exc:
            # A retired or text-only model reports this as a request error;
            # treating it as "cannot see" lets the caller degrade instead of
            # showing the learner a breakage.
            raise VisionUnsupported(str(exc)) from exc

        return (response.choices[0].message.content or "").strip(), _usage(response)

    async def complete_json(
        self, *, system: str, prompt: str, schema: type[BaseModel], max_tokens: int
    ) -> tuple[BaseModel | None, Usage]:
        raw_schema = _strictify(schema.model_json_schema())

        # Preferred: constrained decoding, which guarantees a conforming
        # response. Only the newer Groq models support it, so fall back rather
        # than fail — a missing assessment must never cost the learner a reply.
        attempts: list[dict] = [
            {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__.lower(),
                    "schema": raw_schema,
                    "strict": True,
                },
            },
            {"type": "json_object"},
        ]

        usage = Usage()
        for index, response_format in enumerate(attempts):
            is_fallback = response_format["type"] == "json_object"
            instructions = system
            if is_fallback:
                # json_object mode guarantees valid JSON but not the right
                # shape, and the word "JSON" must appear in the messages.
                instructions = (
                    f"{system}\n\nRespond with a single JSON object matching this "
                    f"schema exactly. Output JSON and nothing else:\n"
                    f"{json.dumps(raw_schema, ensure_ascii=False)}"
                )

            try:
                response = await self.client.chat.completions.create(
                    model=settings.groq_assessor_model,
                    max_tokens=max_tokens,
                    temperature=0.2,
                    response_format=response_format,  # type: ignore[arg-type]
                    messages=[
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt},
                    ],
                )
            except APIError as exc:
                if index + 1 < len(attempts):
                    logger.info(
                        "groq %s mode rejected (%s); retrying in json_object mode",
                        response_format["type"],
                        getattr(exc, "status_code", "?"),
                    )
                    continue
                logger.exception("groq structured call failed")
                return None, usage

            usage = _usage(response)
            content = response.choices[0].message.content or ""
            try:
                return schema.model_validate_json(content), usage
            except ValidationError:
                if index + 1 < len(attempts):
                    logger.info("groq response did not match %s; retrying", schema.__name__)
                    continue
                logger.warning(
                    "groq returned JSON that does not match %s: %.300s",
                    schema.__name__,
                    content,
                )
                return None, usage

        return None, usage
