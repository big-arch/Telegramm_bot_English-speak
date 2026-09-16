from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from bot import personas as personas_mod
from bot.callbacks import LevelCB, PersonaCB, SettingsCB, StyleCB
from bot.db.models import User
from bot.keyboards.common import level_kb, persona_kb, settings_kb, style_kb
from bot.texts import CORRECTION_STYLES, SETTINGS_HEADER

router = Router(name="settings")


def _summary(user: User) -> str:
    persona = personas_mod.get(user.persona_key)
    emoji, title, _ = CORRECTION_STYLES.get(user.correction_style, ("⚖️", "Средне", ""))
    return (
        f"{SETTINGS_HEADER}\n\n"
        f"Собеседник: {persona.emoji} <b>{persona.name}</b> · {persona.accent}\n"
        f"Уровень: <b>{user.productive_level}</b>\n"
        f"Правки: {emoji} <b>{title}</b>\n"
        f"Скорость речи: <b>{personas_mod.speech_speed(persona, user.productive_level):.2f}×</b>"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, user: User) -> None:
    await message.answer(_summary(user), reply_markup=settings_kb())


@router.callback_query(SettingsCB.filter())
async def open_section(
    query: CallbackQuery, callback_data: SettingsCB, user: User
) -> None:
    await query.answer()
    if not isinstance(query.message, Message):
        return

    if callback_data.section == "persona":
        await query.message.edit_text(
            "С кем будешь говорить?", reply_markup=persona_kb(user.productive_level)
        )
    elif callback_data.section == "level":
        await query.message.edit_text(
            "Какой уровень выставить?\n\n"
            "<i>Я всё равно продолжу уточнять его по твоей речи.</i>",
            reply_markup=level_kb(),
        )
    elif callback_data.section == "style":
        lines = ["Насколько строго поправлять?", ""]
        for emoji, title, description in CORRECTION_STYLES.values():
            lines.append(f"{emoji} <b>{title}</b> — {description}")
        await query.message.edit_text("\n".join(lines), reply_markup=style_kb())


# These handlers carry no state filter on purpose: onboarding registers its own
# state-filtered versions in an earlier router, so those win during onboarding
# and these catch the same buttons pressed from /settings afterwards.


@router.callback_query(PersonaCB.filter())
async def change_persona(
    query: CallbackQuery, callback_data: PersonaCB, session: DbSession, user: User
) -> None:
    persona = personas_mod.get(callback_data.key)
    user.persona_key = persona.key
    await session.commit()
    await query.answer(f"Теперь говоришь с {persona.name}")
    if isinstance(query.message, Message):
        await query.message.edit_text(_summary(user), reply_markup=settings_kb())


@router.callback_query(LevelCB.filter())
async def change_level(
    query: CallbackQuery, callback_data: LevelCB, session: DbSession, user: User
) -> None:
    levels = ["A1", "A2", "B1", "B2", "C1", "C2"]
    user.productive_level = callback_data.level
    user.level_score = levels.index(callback_data.level) * 20 + 10
    user.receptive_level = levels[min(levels.index(callback_data.level) + 1, 5)]
    await session.commit()
    await query.answer("Уровень обновлён")
    if isinstance(query.message, Message):
        await query.message.edit_text(_summary(user), reply_markup=settings_kb())


@router.callback_query(StyleCB.filter())
async def change_style(
    query: CallbackQuery, callback_data: StyleCB, session: DbSession, user: User
) -> None:
    user.correction_style = callback_data.style
    await session.commit()
    await query.answer("Готово")
    if isinstance(query.message, Message):
        await query.message.edit_text(_summary(user), reply_markup=settings_kb())
