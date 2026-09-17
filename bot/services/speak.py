"""Sending the tutor's reply as a Telegram voice note."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from bot import personas as personas_mod
from bot.db.repositories import AudioCacheRepo
from bot.services import tts

logger = logging.getLogger(__name__)


async def send_spoken(
    bot: Bot,
    db: DbSession,
    *,
    chat_id: int,
    text: str,
    persona: personas_mod.Persona,
    level: str,
    caption: str | None = None,
    reply_markup=None,
) -> Message | None:
    """Speak `text` in the persona's voice, then send the text alongside.

    Both, not either: the audio is the practice, the text is what they check
    themselves against and can re-read. Competitors that send audio only make
    learners replay a message five times to catch one word.

    Cached by content hash — a repeated line costs one API call, not a new
    synthesis every time.
    """
    speed = personas_mod.speech_speed(persona, level)
    key = tts.cache_key(text, persona.key, speed)
    cache = AudioCacheRepo(db)

    file_id = await cache.get(key)
    if file_id:
        try:
            return await bot.send_voice(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        except TelegramAPIError:
            # file_id can be invalidated; fall through and re-synthesise.
            logger.warning("cached file_id rejected, re-synthesising")

    audio = await tts.synthesize(
        text,
        edge_voice=persona.edge_voice,
        elevenlabs_voice_id=persona.elevenlabs_voice_id,
        openai_voice=persona.openai_voice,
        speed=speed,
    )
    if audio is None:
        # Voice is a nicety; never let a synthesis failure cost them the reply.
        return await bot.send_message(chat_id, text, reply_markup=reply_markup)

    message = await bot.send_voice(
        chat_id,
        BufferedInputFile(audio, filename=f"{persona.key}.ogg"),
        caption=caption,
        reply_markup=reply_markup,
    )
    if message.voice:
        await cache.put(content_hash=key, file_id=message.voice.file_id, voice_key=persona.key)
        await db.commit()
    return message
