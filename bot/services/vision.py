"""Looking at a photo the learner sends.

Describing a picture is a speaking skill in its own right — it is what
Cambridge and IELTS speaking papers test, because it forces vocabulary the
learner would otherwise avoid. Doing it on *their* photo rather than a stock
image is the difference between an exercise and a conversation: they already
know what is in it and want to say something about it.

This module only turns pixels into a factual description. The talking is done
by the ordinary conversation machinery, with that description dropped into the
history — so the persona, the level cap and the memory all keep working, and
the tutor can still refer back to the photo ten turns later.

**Every configured provider is tried, not just the preferred one.** Vision was
the one path pinned to a single vendor, so when that vendor retired a model the
symptom was "the bot can't see my photo" while conversation carried on
perfectly — a failure that looks like a broken feature and is really a dead
model name. The learner does not care which company looked at their picture.
"""

from __future__ import annotations

import logging

from bot.config import settings
from bot.services.backends import Usage
from bot.services.backends.base import VisionUnsupported

logger = logging.getLogger(__name__)

# Deliberately factual and unglamorous. This text is fed to the tutor, not to
# the learner, and a flowery description would put words in the tutor's mouth
# that the learner never gets to reach for themselves.
DESCRIBE_PROMPT = """Describe this photograph plainly for a colleague who cannot see it.

Cover, in 2-4 sentences: the setting, the main subjects and what they are doing, \
anything notable about the time of day, weather, or mood.

Do not interpret, do not speculate about who the people are, and do not use \
flowery language. If the image is unclear, say so. If it contains text, quote it.
Answer in English."""


def available() -> bool:
    return bool(_candidates())


def _candidates() -> list[str]:
    """Providers that could look at a photo, best first.

    The configured preference leads; anything else with a key follows. Two free
    accounts failing at the same moment is far less likely than one of them
    retiring a model, which has now happened twice.
    """
    preferred = settings.resolved_vision_provider
    if preferred == "off":
        return []

    ordered = [preferred]
    for provider, key in (
        ("gemini", settings.gemini_api_key),
        ("groq", settings.groq_api_key),
        ("anthropic", settings.anthropic_api_key),
    ):
        if provider not in ordered and key is not None:
            ordered.append(provider)
    return ordered


def _backend(provider: str):
    from bot.services.backends.anthropic_backend import AnthropicBackend
    from bot.services.backends.gemini_backend import GeminiBackend
    from bot.services.backends.groq_backend import GroqBackend

    if provider == "gemini":
        return GeminiBackend()
    if provider == "groq":
        return GroqBackend()
    if provider == "anthropic":
        return AnthropicBackend()
    raise VisionUnsupported(f"unknown vision provider {provider!r}")


async def describe(
    image: bytes, *, mime: str = "image/jpeg"
) -> tuple[str | None, Usage, list[str]]:
    """Return a factual description, the usage, and a note per provider tried.

    Never raises: a tutor who cannot see a photo can still ask the learner to
    describe it, which is the better exercise anyway. The notes exist because
    this runs where nobody in the conversation can read a log — "couldn't see
    it" is a symptom, and the learner deserves to be able to hand over a cause.
    """
    providers = _candidates()
    if not providers:
        return None, Usage(), ["no vision provider is configured"]

    if len(image) > settings.max_photo_bytes:
        return None, Usage(), [f"photo is {len(image) // 1024} KB, over the limit"]

    notes: list[str] = []
    for provider in providers:
        try:
            text, usage = await _backend(provider).describe_image(
                image=image, mime=mime, prompt=DESCRIBE_PROMPT, max_tokens=400
            )
        except VisionUnsupported as exc:
            notes.append(f"{provider}: cannot see: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - every provider fails its own way
            logger.exception("vision call failed on %s", provider)
            notes.append(f"{provider}: {type(exc).__name__}: {str(exc)[:200]}")
            continue

        if text:
            notes.append(f"{provider}: ok")
            return text, usage, notes
        notes.append(f"{provider}: returned nothing")

    return None, Usage(), notes


def as_history_note(description: str) -> str:
    """How the photo enters the conversation the model sees.

    Marked as context rather than as something the learner said, so the
    assessor never grades the model's own words, and the tutor knows the
    picture came from them.
    """
    return (
        "[The learner has just sent you a photograph. You can see it. "
        f"It shows: {description}]\n\n"
        "Reply in ONE OR TWO sentences, the way a friend does when shown a "
        "picture: name the single thing that caught your eye, then ask them "
        "something about it. Do NOT describe the photo back to them and do NOT "
        "list what is in it — they took it, they know. Wrong: \"I see a sunset "
        "with pine trees and clouds.\" Right: \"Those clouds are unreal. Where "
        "was this taken?\""
    )
