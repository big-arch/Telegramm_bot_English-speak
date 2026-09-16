"""Text to speech, with speed control and caching.

Two things here are not incidental:

1. **Speed is a function of the learner's level.** "The AI speaks too fast" is a
   recurring complaint about every competitor. Slowing a beginner's tutor down
   costs nothing and removes the single most common reason people give up.

2. **Everything synthesised is cached by content hash to a Telegram file_id.**
   Re-sending by file_id is free and instant. Without it, the same prompt line
   costs another synthesis every time it is used — the difference between a
   trivial bill and a large one.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

import httpx
from openai import AsyncOpenAI, OpenAIError

from bot.config import settings

logger = logging.getLogger(__name__)

_openai = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVEN_MODEL = "eleven_turbo_v2_5"


def cache_key(text: str, voice: str, speed: float) -> str:
    """Stable hash of everything that affects the produced audio."""
    raw = f"{voice}|{speed:.2f}|{text}".encode()
    return hashlib.sha256(raw).hexdigest()


async def _ffmpeg(data: bytes, args: list[str]) -> bytes:
    """Run ffmpeg over stdin/stdout without blocking the event loop."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
        *args, "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(data)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode()[:400]}")
    return out


async def _to_voice_ogg(data: bytes, speed: float = 1.0) -> bytes:
    """Convert to OGG/OPUS — the only format Telegram renders as a voice bubble.

    An MP3 sent via answer_voice arrives as a file attachment instead, which
    loses the waveform and inline playback.

    `atempo` is capped at [0.5, 2.0] per filter instance; our range is well
    inside that, so one pass is enough.
    """
    args = ["-c:a", "libopus", "-b:a", "48k", "-ar", "48000", "-ac", "1", "-f", "ogg"]
    if abs(speed - 1.0) > 0.01:
        args = ["-filter:a", f"atempo={max(0.5, min(2.0, speed)):.2f}", *args]
    return await _ffmpeg(data, args)


async def _synthesize_elevenlabs(text: str, voice_id: str, speed: float) -> bytes:
    assert settings.elevenlabs_api_key is not None
    async with httpx.AsyncClient(timeout=30.0) as http:
        response = await http.post(
            ELEVEN_URL.format(voice_id=voice_id),
            headers={
                "xi-api-key": settings.elevenlabs_api_key.get_secret_value(),
                "accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": ELEVEN_MODEL,
                "voice_settings": {
                    "stability": 0.45,
                    "similarity_boost": 0.75,
                    "style": 0.2,
                },
            },
        )
        response.raise_for_status()
        mp3 = response.content
    # ElevenLabs returns mp3; speed is applied during the conversion pass.
    return await _to_voice_ogg(mp3, speed)


async def _synthesize_openai(text: str, voice: str, speed: float) -> bytes:
    response = await _openai.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
        response_format="opus",  # already Ogg Opus — no conversion needed
        speed=max(0.25, min(4.0, speed)),
    )
    return response.content


async def synthesize(
    text: str,
    *,
    elevenlabs_voice_id: str,
    openai_voice: str,
    speed: float = 1.0,
) -> bytes | None:
    """Produce Telegram-ready OGG/OPUS bytes. Returns None if synthesis failed.

    Voice is a nicety; a failed synthesis must never cost the learner their
    reply. Callers fall back to sending the text alone.
    """
    if not text.strip():
        return None

    if settings.uses_elevenlabs:
        try:
            return await _synthesize_elevenlabs(text, elevenlabs_voice_id, speed)
        except (httpx.HTTPError, RuntimeError):
            logger.exception("elevenlabs synthesis failed; falling back to openai")

    try:
        return await _synthesize_openai(text, openai_voice, speed)
    except (OpenAIError, RuntimeError):
        logger.exception("openai synthesis failed")
        return None
