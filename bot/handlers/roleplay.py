"""Choosing and starting a role-play scene, and celebrating the end of one.

What happens *during* a scene lives in the ordinary conversation handlers —
a scene is a conversation with a brief and a checklist, not a separate mode
with its own voice path. This module owns only the edges: the list, the
start, and the finish.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from bot import personas as personas_mod
from bot import scenarios as scenarios_mod
from bot.callbacks import ScenarioCB
from bot.db.models import Session, User
from bot.db.repositories import SessionRepo
from bot.keyboards.common import opening_kb, scenario_done_kb, scenarios_kb
from bot.services import flair
from bot.services.speak import send_spoken

logger = logging.getLogger(__name__)
router = Router(name="roleplay")

MENU = (
    "🎭 <b>Ролевые сценарии</b>\n\n"
    "Сцена из жизни и задача, которую нужно решить по-английски. "
    "Цели отмечаются сами, как только ты их выполнил, — говори как обычно.\n\n"
    "<i>⭐ — под твой уровень</i>"
)


@router.message(Command("roleplay"))
async def cmd_roleplay(message: Message, user: User) -> None:
    await message.answer(MENU, reply_markup=scenarios_kb(user.productive_level))


@router.callback_query(ScenarioCB.filter())
async def pick_scenario(
    query: CallbackQuery,
    callback_data: ScenarioCB,
    session: DbSession,
    user: User,
    bot: Bot,
) -> None:
    await query.answer()
    if not isinstance(query.message, Message):
        return

    if callback_data.key == "menu":
        await query.message.answer(MENU, reply_markup=scenarios_kb(user.productive_level))
        return

    scenario = scenarios_mod.get(callback_data.key)
    if scenario is None:
        return

    convo = await SessionRepo(session).start(
        user_id=user.id, persona_key=user.persona_key, topic_id=None
    )
    convo.scenario_key = scenario.key
    convo.goals_done = ""
    convo.opening_line = scenario.opening

    chat_id = query.message.chat.id
    # The list is replaced by the card, so the chat reads as a scene rather
    # than a menu with a scene underneath.
    try:
        await query.message.delete()
    except TelegramAPIError:
        pass

    card = await bot.send_message(chat_id, scenarios_mod.card(scenario, set()))
    convo.card_message_id = card.message_id
    await session.commit()

    # Pinned quietly, so the checklist stays in view however long the scene
    # runs. Unpinned again when it ends.
    try:
        await bot.pin_chat_message(chat_id, card.message_id, disable_notification=True)
    except TelegramAPIError:
        pass

    persona = personas_mod.get(user.persona_key)
    await send_spoken(
        bot,
        session,
        chat_id=chat_id,
        text=scenario.opening,
        persona=persona,
        level=user.productive_level,
        caption=scenario.opening,
        reply_markup=opening_kb(),
    )


async def after_turn(
    bot: Bot,
    *,
    chat_id: int,
    convo: Session,
    learner_message_id: int,
    goals_met: tuple[int, ...],
    complete: bool,
) -> None:
    """Update the checklist and mark the moment. Called after the partner's reply.

    Nothing here is allowed to fail the turn: the reply has already been sent,
    and a checklist that did not update is a much smaller problem than an
    error message after a perfectly good exchange.
    """
    scenario = scenarios_mod.get(convo.scenario_key)
    if scenario is None or not goals_met:
        return

    done = scenarios_mod.parse_done(convo.goals_done)

    # 🔥 on the very sentence that did it — more precise than any reply.
    await flair.react(bot, chat_id, learner_message_id, "🔥")

    if convo.card_message_id:
        try:
            await bot.edit_message_text(
                scenarios_mod.card(scenario, done, finished=complete),
                chat_id=chat_id,
                message_id=convo.card_message_id,
            )
        except TelegramAPIError:
            logger.info("could not update the scenario card for session %s", convo.id)

    if not complete:
        names = ", ".join(
            html.escape(scenario.goals[i].ru.lower(), quote=False) for i in goals_met
        )
        try:
            await bot.send_message(
                chat_id,
                f"✅ <i>{names}</i> · {len(done)} из {len(scenario.goals)}",
                disable_notification=True,
            )
        except TelegramAPIError:
            pass
        return

    if convo.card_message_id:
        try:
            await bot.unpin_chat_message(chat_id, message_id=convo.card_message_id)
        except TelegramAPIError:
            pass

    await flair.send_celebration(
        bot,
        chat_id,
        f"🏆 <b>Сценарий «{scenario.title_ru}» пройден!</b>\n\n"
        f"Все {len(scenario.goals)} задачи — по-английски, вслух. "
        "В реальной жизни это ровно то, что нужно было сделать.\n\n"
        "Можешь договорить сцену — или получить разбор.",
        reply_markup=scenario_done_kb(convo.id),
    )
