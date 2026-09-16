"""Asking for a picture directly, and finding out why one did not arrive.

This exists because of a specific afternoon: the tutor kept promising photos
that never came, and the bot runs on a host whose logs nobody in the
conversation could read. Guessing at it cost several deploys.

So the lookup reports on itself. `/photo hamburger` sends the picture when it
can, and when it cannot it prints exactly which source refused and with what
error — something a person can screenshot and hand over. A feature that can
explain its own failure is one that gets fixed in a single round instead of
five.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.services import images

logger = logging.getLogger(__name__)
router = Router(name="photo")

USAGE = (
    "Напиши, что показать: <code>/photo hamburger</code>\n\n"
    "Работает и в обычном разговоре — просто попроси по-английски: "
    "<i>«show me the Eiffel Tower»</i>."
)

REFUSED = (
    "Такое я не ищу 🙂 Давай что-нибудь другое — место, еду, здание, предмет."
)


@router.message(Command("photo"))
async def cmd_photo(message: Message, command: CommandObject, bot: Bot) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer(USAGE)
        return

    if not images.allowed(query):
        await message.answer(REFUSED)
        return

    status = await message.answer("🔍 Ищу…")
    url, notes = await images.look_up(query)

    if url:
        try:
            await bot.send_photo(message.chat.id, url, caption=query)
            await status.delete()
            return
        except TelegramAPIError as exc:
            # Telegram fetches the URL itself and sometimes refuses one. Worth
            # reporting rather than swallowing: it looks identical to "not
            # found" from the outside, and it is a completely different fault.
            notes.append(f"telegram refused the url: {exc}")

    logger.info("photo diagnostics for %r: %s", query, "; ".join(notes))
    report = "\n".join(f"• <code>{note}</code>" for note in notes)
    await status.edit_text(
        f"Не получилось найти картинку для <b>{query}</b>.\n\n"
        f"Что ответил каждый источник:\n{report}\n\n"
        "<i>Покажи это Claude — тут видно, что именно сломалось.</i>"
    )
