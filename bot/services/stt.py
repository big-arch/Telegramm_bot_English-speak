"""Speech recognition.

Word-level timestamps are the point. Without them every fluency metric is
unavailable and you are left grading a transcript, which is what the competitors
do and why their feedback feels thin.

Two providers, same OpenAI-shaped API:

- **groq** (free): Whisper large v3 turbo. Free tier as of 2026 is ~2,000
  requests and 28,800 audio-seconds per day — eight hours of speech, daily,
  at no cost. This is the default.
- **openai** (paid): same model family, no daily ceiling.

If a provider returns no word timestamps, fluency degrades to None rather than
failing: the conversation still works, only the speech metrics go quiet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

from openai import AsyncOpenAI, OpenAIError

from bot.config import settings

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Whisper is used deliberately over newer transcription models: those return
# better text but do not expose word timestamps, and the timestamps are worth
# more here than a marginal accuracy gain.
MODELS = {
    "groq": "whisper-large-v3-turbo",
    "openai": "whisper-1",
}

# Without this, Whisper quietly "repairs" non-native grammar into fluent
# English, erasing exactly what we are trying to measure and correct.
LEARNER_PROMPT = (
    "This is a language learner speaking English. Transcribe exactly what was said, "
    "including grammatical errors, hesitations and repetitions. Do not correct the "
    "speaker."
)


@dataclass
class Transcript:
    text: str
    duration: float
    words: list[dict] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@lru_cache(maxsize=1)
def _client() -> AsyncOpenAI:
    provider = settings.stt_provider.lower()
    if provider == "groq":
        if settings.groq_api_key is None:
            raise RuntimeError("STT_PROVIDER=groq but GROQ_API_KEY is not set")
        return AsyncOpenAI(
            api_key=settings.groq_api_key.get_secret_value(), base_url=GROQ_BASE_URL
        )
    if provider == "openai":
        if settings.openai_api_key is None:
            raise RuntimeError("STT_PROVIDER=openai but OPENAI_API_KEY is not set")
        return AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
    raise RuntimeError(f"Unknown STT_PROVIDER={provider!r}. Supported: groq (free), openai.")


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> Transcript | None:
    """Transcribe a Telegram voice note. Returns None if recognition failed."""
    model = MODELS.get(settings.stt_provider.lower(), MODELS["groq"])

    try:
        result = await _client().audio.transcriptions.create(
            model=model,
            file=(filename, audio),
            response_format="verbose_json",
            timestamp_granularities=["word"],
            language="en",
            temperature=0.0,
            prompt=LEARNER_PROMPT,
        )
    except OpenAIError:
        logger.exception("transcription failed via %s", settings.stt_provider)
        return None

    raw_words = getattr(result, "words", None) or []
    words = [
        {"word": _attr(w, "word"), "start": _attr(w, "start"), "end": _attr(w, "end")}
        for w in raw_words
    ]
    words = [w for w in words if w["start"] is not None and w["end"] is not None]

    return Transcript(
        text=(getattr(result, "text", "") or "").strip(),
        duration=float(getattr(result, "duration", 0.0) or 0.0),
        words=words,
    )


def _attr(obj, name):
    """Providers return either objects or plain dicts for the word list."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
