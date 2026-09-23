"""Sending a conversation partner's portrait into the chat.

The moment someone picks who they will talk to is the moment the product has
to feel like more than a text box. A portrait there is what makes the choice
feel like meeting someone.

Uploaded once per process and then sent by file_id: Telegram keeps the file,
so every later send is a reference rather than another 60 KB over the wire.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from bot import personas as personas_mod

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent.parent / "assets" / "personas"

_file_ids: dict[str, str] = {}


def path_for(key: str) -> Path | None:
    candidate = ASSETS / f"{key}.jpg"
    return candidate if candidate.exists() else None


def caption_for(persona: personas_mod.Persona) -> str:
    return (
        f"{persona.emoji} <b>{persona.name}</b> · {persona.accent}\n"
        f"<i>{persona.tagline_ru}</i>"
    )


async def send(
    bot: Bot,
    chat_id: int,
    persona: personas_mod.Persona,
    *,
    caption: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Send the portrait card. False when there is none, so callers can fall
    back to text — a missing picture must never cost the learner the message
    that was supposed to go with it."""
    source = _file_ids.get(persona.key)
    if source is None:
        path = path_for(persona.key)
        if path is None:
            return False
        source = FSInputFile(path)

    try:
        message = await bot.send_photo(
            chat_id,
            source,
            caption=caption if caption is not None else caption_for(persona),
            reply_markup=reply_markup,
        )
    except TelegramAPIError:
        logger.exception("could not send the portrait for %s", persona.key)
        _file_ids.pop(persona.key, None)
        return False

    if message.photo:
        _file_ids[persona.key] = message.photo[-1].file_id
    return True
