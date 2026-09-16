"""Text to speech, with speed control and caching.

Three providers, one interface:

- **edge** (free, default): Microsoft's neural voices, the same ones Edge uses
  for read-aloud. No API key, no account, no per-character cost, and it has real
  regional accents — which is exactly what the personas need. It is an
  unofficial endpoint, so treat it as a dependency that can break: if it does,
  flip TTS_PROVIDER and nothing else changes.
- **openai** (cheap): ~$15 per million characters.
- **elevenlabs** (best, priciest): ~6-12x OpenAI, noticeably more alive.

Two things here are not incidental:

1. **Speed is a function of the learner's level.** "The AI speaks too fast" is a
   recurring complaint about every competitor. Slowing a beginner's tutor down
   costs nothing and removes a common reason people give up.

2. **Everything synthesised is cached by content hash to a Telegram file_id.**
   Re-sending by file_id is free and instant.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

import httpx

from bot.config import settings

logger = logging.getLogger(__name__)

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVEN_MODEL = "eleven_turbo_v2_5"


def cache_key(text: str, voice: str, speed: float) -> str:
    """Stable hash of everything that affects the produced audio."""
    raw = f"{settings.tts_provider}|{voice}|{speed:.2f}|{text}".encode()
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

    An MP3 sent via answer_voice arrives as a file attachment instead, losing
    the waveform and inline playback.
    """
    args = ["-c:a", "libopus", "-b:a", "48k", "-ar", "48000", "-ac", "1", "-f", "ogg"]
    if abs(speed - 1.0) > 0.01:
        # atempo is valid on [0.5, 2.0]; our range sits well inside it.
        args = ["-filter:a", f"atempo={max(0.5, min(2.0, speed)):.2f}", *args]
    return await _ffmpeg(data, args)


async def _synthesize_edge(text: str, voice: str, speed: float) -> bytes:
    import edge_tts

    # edge-tts applies rate natively, so no atempo pass and no quality loss.
    percent = round((speed - 1.0) * 100)
    rate = f"{percent:+d}%"

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    mp3 = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])
    if not mp3:
        raise RuntimeError("edge-tts returned no audio")
    return await _to_voice_ogg(bytes(mp3), speed=1.0)


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
    return await _to_voice_ogg(mp3, speed)


async def _synthesize_openai(text: str, voice: str, speed: float) -> bytes:
    from openai import AsyncOpenAI

    assert settings.openai_api_key is not None
    client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
    response = await client.audio.speech.create(
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
    edge_voice: str,
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

    provider = settings.tts_provider.lower()

    try:
        if provider == "edge":
            return await _synthesize_edge(text, edge_voice, speed)
        if provider == "elevenlabs" and settings.elevenlabs_api_key:
            return await _synthesize_elevenlabs(text, elevenlabs_voice_id, speed)
        if provider == "openai" and settings.openai_api_key:
            return await _synthesize_openai(text, openai_voice, speed)
    except Exception:
        logger.exception("%s synthesis failed", provider)

    # Fall back to the free provider before giving up entirely.
    if provider != "edge":
        try:
            return await _synthesize_edge(text, edge_voice, speed)
        except Exception:
            logger.exception("edge fallback synthesis failed")

    return None
