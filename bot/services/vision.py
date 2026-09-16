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
    return settings.resolved_vision_provider != "off"


def _backend():
    from bot.services.backends.anthropic_backend import AnthropicBackend
    from bot.services.backends.gemini_backend import GeminiBackend
    from bot.services.backends.groq_backend import GroqBackend

    provider = settings.resolved_vision_provider
    if provider == "gemini":
        return GeminiBackend()
    if provider == "groq":
        return GroqBackend()
    if provider == "anthropic":
        return AnthropicBackend()
    raise VisionUnsupported(f"vision provider is {provider!r}")


async def describe(image: bytes, *, mime: str = "image/jpeg") -> tuple[str | None, Usage]:
    """Return a factual description, or None when the photo cannot be read.

    Never raises: a tutor who cannot see a photo can still ask the learner to
    describe it, which is the better exercise anyway.
    """
    if not available():
        return None, Usage()

    if len(image) > settings.max_photo_bytes:
        logger.info("photo too large: %d bytes", len(image))
        return None, Usage()

    try:
        text, usage = await _backend().describe_image(
            image=image, mime=mime, prompt=DESCRIBE_PROMPT, max_tokens=400
        )
    except VisionUnsupported as exc:
        logger.warning("vision unavailable: %s", exc)
        return None, Usage()
    except Exception:
        logger.exception("vision call failed")
        return None, Usage()

    return (text or None), usage


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
