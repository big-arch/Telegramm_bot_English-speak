from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from bot import personas as personas_mod
from bot.callbacks import GoalCB, LevelCB, PersonaCB
from bot.db.models import User
from bot.keyboards.common import goal_kb, level_kb, persona_kb
from bot.services import portraits
from bot.states import Onboarding
from bot.texts import (
    ASK_GOAL,
    ASK_LEVEL,
    ASK_PERSONA,
    ONBOARDING_DONE,
    WELCOME,
)

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await state.set_state(Onboarding.choosing_level)
    await message.answer(WELCOME)
    await message.answer(ASK_LEVEL, reply_markup=level_kb())


@router.callback_query(LevelCB.filter(), Onboarding.choosing_level)
async def pick_level(
    query: CallbackQuery,
    callback_data: LevelCB,
    state: FSMContext,
    session: DbSession,
    user: User,
) -> None:
    level = callback_data.level
    user.productive_level = level
    user.receptive_level = level
    user.level_score = ["A1", "A2", "B1", "B2", "C1", "C2"].index(level) * 20 + 10
    await session.commit()

    await state.set_state(Onboarding.choosing_persona)
    if isinstance(query.message, Message):
        await query.message.edit_text(ASK_PERSONA, reply_markup=persona_kb(level))
    await query.answer()


@router.callback_query(PersonaCB.filter(), Onboarding.choosing_persona)
async def pick_persona(
    query: CallbackQuery,
    callback_data: PersonaCB,
    state: FSMContext,
    session: DbSession,
    user: User,
    bot: Bot,
) -> None:
    persona = personas_mod.get(callback_data.key)
    user.persona_key = persona.key
    user.correction_style = persona.correction_style
    await session.commit()

    await state.set_state(Onboarding.choosing_goal)
    await query.answer()
    if not isinstance(query.message, Message):
        return

    # Choosing a partner is the moment the product has to feel like meeting
    # someone rather than filling in a form, so they get a portrait. The picker
    # is replaced rather than left above it: a list of seven names sitting over
    # the one you chose reads as a menu you forgot to close.
    chat_id = query.message.chat.id
    if await portraits.send(bot, chat_id, persona):
        await query.message.delete()
        await bot.send_message(chat_id, ASK_GOAL, reply_markup=goal_kb())
    else:
        await query.message.edit_text(
            f"{persona.emoji} <b>{persona.name}</b> — {persona.accent}\n"
            f"<i>{persona.tagline_ru}</i>\n\n{ASK_GOAL}",
            reply_markup=goal_kb(),
        )


@router.callback_query(GoalCB.filter(), Onboarding.choosing_goal)
async def pick_goal(
    query: CallbackQuery,
    callback_data: GoalCB,
    state: FSMContext,
    session: DbSession,
    user: User,
) -> None:
    user.goal = callback_data.key
    await session.commit()
    await state.clear()

    if isinstance(query.message, Message):
        await query.message.edit_text(ONBOARDING_DONE)
    await query.answer()


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(ONBOARDING_DONE)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    # Orphaned FSM state eats the user's next unrelated message, so /cancel
    # always clears rather than checking whether anything was in progress.
    await state.clear()
    await message.answer("Ок, отменил.")
