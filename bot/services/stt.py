"""Speech recognition.

Word-level timestamps are the point. Without them every fluency metric is
unavailable and you are left grading a transcript, which is what the competitors
do and why their feedback feels thin.

`whisper-1` is used deliberately: the newer transcription models return richer
text but do not expose word timestamps, and the timestamps are worth more here
than a marginal accuracy gain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI, OpenAIError

from bot.config import settings

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


@dataclass
class Transcript:
    text: str
    duration: float
    words: list[dict] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> Transcript | None:
    """Transcribe a Telegram voice note. Returns None if recognition failed.

    A prompt is passed to bias Whisper towards learner English: without it, the
    model tends to "repair" non-native grammar into fluent English, which
    silently erases exactly what we are trying to measure and correct.
    """
    try:
        result = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio),
            response_format="verbose_json",
            timestamp_granularities=["word"],
            language="en",
            temperature=0.0,
            prompt=(
                "This is a language learner speaking English. Transcribe exactly what "
                "was said, including grammatical errors, hesitations and repetitions. "
                "Do not correct the speaker."
            ),
        )
    except OpenAIError:
        logger.exception("transcription failed")
        return None

    words = [
        {"word": w.word, "start": w.start, "end": w.end}
        for w in (getattr(result, "words", None) or [])
    ]
    return Transcript(
        text=(result.text or "").strip(),
        duration=float(getattr(result, "duration", 0.0) or 0.0),
        words=words,
    )
