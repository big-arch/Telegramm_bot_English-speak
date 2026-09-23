"""The small native touches that make a bot feel made rather than assembled.

Telegram gives bots three things most never use, and each replaces a message
with something better than a message:

- **Message effects** — the confetti that bursts over a message in a private
  chat. Kept for moments that deserve it (a scene finished, a streak
  milestone); used on everything, it becomes wallpaper.
- **Reactions** on the learner's own message. A 🔥 on the sentence that met a
  goal says "that one" more precisely than any reply could, and adds nothing to
  scroll past.
- **Chat actions** — "recording a voice message…" in the header while speech is
  synthesised, which is what a person on the other end would be doing.

Every one of them is decoration, so every one of them fails silently. The
effect ids in particular are Telegram's and can be withdrawn; a rejected effect
is retried as a plain message rather than costing the learner the message.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message, ReactionTypeEmoji

logger = logging.getLogger(__name__)

# Telegram's built-in message effects for private chats.
CONFETTI = "5046509860389126442"   # 🎉
FIRE = "5104841245755180586"       # 🔥


async def send_celebration(bot: Bot, chat_id: int, text: str, *, effect: str = CONFETTI,
                           **kwargs) -> Message | None:
    """Send with an effect; if Telegram refuses the effect, send without it."""
    try:
        return await bot.send_message(chat_id, text, message_effect_id=effect, **kwargs)
    except TelegramBadRequest:
        logger.info("message effect %s refused; sending plain", effect)
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramAPIError:
        logger.exception("celebration message failed")
        return None


async def react(bot: Bot, chat_id: int, message_id: int, emoji: str = "🔥") -> None:
    """Put a reaction on one of the learner's messages. Never raises."""
    try:
        await bot.set_message_reaction(
            chat_id, message_id, reaction=[ReactionTypeEmoji(emoji=emoji)]
        )
    except TelegramAPIError:
        logger.info("reaction %s refused on %s", emoji, message_id)
