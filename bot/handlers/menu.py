"""The always-visible panel and the "Ещё" menu behind it.

The Menu button beside the message field opens the home screen now, and
Telegram gives that spot to one thing only — a web app *or* the command list.
Commands still work when typed, but nobody guesses that "/" is the way in, and
a bot whose features are invisible has fewer features than its code.

So the panel. Every button here is a front door to a handler that already
exists; nothing is reimplemented, which is what keeps a button and its slash
command from drifting apart.

Registered before the conversation router: its catch-all would otherwise take
"🏁 Закончить" as something said to the barista.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from bot.callbacks import MenuCB
from bot.db.models import User
from bot.handlers import photo, progress, review, roleplay, settings, start
from bot.handlers import conversation
from bot.keyboards.common import FINISH, MORE, TALK, WORDS, main_kb, more_kb
from bot.texts import PANEL_ON

router = Router(name="menu")

MORE_TITLE = "☰ <b>Всё остальное</b>"

PHOTO_HOWTO = (
    "🖼 Напиши <code>/photo</code> и что показать, например "
    "<code>/photo Brooklyn Bridge</code>.\n\n"
    "Или просто попроси в разговоре: <i>«show me a red panda»</i>."
)


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    """Bring the panel back — for anyone who folded it away or never had it."""
    await message.answer(PANEL_ON, reply_markup=main_kb())


# The panel's first version had a separate scenes button. Panels already sent
# keep showing it until the next /menu, so it still has to go somewhere.
LEGACY_ROLEPLAY = "🎭 Сценарий"


@router.message(F.text.in_({TALK, LEGACY_ROLEPLAY}))
async def press_talk(message: Message, session: DbSession, user: User) -> None:
    await roleplay.show_picker(message, session, user)


@router.message(F.text == WORDS)
async def press_words(message: Message, session: DbSession, user: User) -> None:
    await review.cmd_review(message, session, user)


@router.message(F.text == FINISH)
async def press_finish(message: Message, session: DbSession, user: User, bot: Bot) -> None:
    await conversation.cmd_finish(message, session, user, bot)


@router.message(F.text == MORE)
async def press_more(message: Message) -> None:
    await message.answer(MORE_TITLE, reply_markup=more_kb())


@router.callback_query(MenuCB.filter())
async def pick_more(
    query: CallbackQuery,
    callback_data: MenuCB,
    session: DbSession,
    user: User,
    bot: Bot,
) -> None:
    await query.answer()
    message = query.message
    if not isinstance(message, Message):
        return

    action = callback_data.action
    if action == "finish":  # moved to the panel; old menus still send it
        await conversation.cmd_finish(message, session, user, bot)
    elif action == "progress":
        await progress.cmd_progress(message, session, user)
    elif action == "mistakes":
        await progress.cmd_mistakes(message, session, user)
    elif action == "settings":
        await settings.cmd_settings(message, user)
    elif action == "photo":
        await message.answer(PHOTO_HOWTO)
    elif action == "help":
        await start.cmd_help(message)
    elif action == "diag":
        await photo.cmd_diag(message)
