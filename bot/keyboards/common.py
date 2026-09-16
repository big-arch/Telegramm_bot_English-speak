from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import personas as personas_mod
from bot.callbacks import (
    GoalCB,
    LevelCB,
    PersonaCB,
    ReviewCB,
    SettingsCB,
    StyleCB,
    TopicCB,
)
from bot.db.models import Topic
from bot.texts import CORRECTION_STYLES, GOALS, LEVEL_HINTS


def level_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for level, hint in LEVEL_HINTS.items():
        kb.button(text=f"{level} — {hint}", callback_data=LevelCB(level=level))
    kb.adjust(1)
    return kb.as_markup()


def persona_kb(level: str) -> InlineKeyboardMarkup:
    """All personas, the ones suited to this level marked and listed first."""
    kb = InlineKeyboardBuilder()
    for persona in personas_mod.suggest_for_level(level):
        mark = "⭐ " if personas_mod.suits(persona, level) else ""
        kb.button(
            text=f"{mark}{persona.emoji} {persona.name} · {persona.accent}",
            callback_data=PersonaCB(key=persona.key),
        )
    kb.adjust(1)
    return kb.as_markup()


def goal_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, (emoji, title) in GOALS.items():
        kb.button(text=f"{emoji} {title}", callback_data=GoalCB(key=key))
    kb.adjust(1)
    return kb.as_markup()


def topics_kb(topics: list[Topic]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for topic in topics:
        kb.button(
            text=f"{topic.emoji} {topic.title_ru}",
            callback_data=TopicCB(topic_id=topic.id),
        )
    kb.adjust(1)
    return kb.as_markup()


def style_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, (emoji, title, _) in CORRECTION_STYLES.items():
        kb.button(text=f"{emoji} {title}", callback_data=StyleCB(style=key))
    kb.adjust(3)
    return kb.as_markup()


def settings_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎭 Собеседник", callback_data=SettingsCB(section="persona"))
    kb.button(text="📈 Уровень", callback_data=SettingsCB(section="level"))
    kb.button(text="🎯 Строгость правок", callback_data=SettingsCB(section="style"))
    kb.adjust(1)
    return kb.as_markup()


def review_kb(card_id: int) -> InlineKeyboardMarkup:
    """Four-button SRS grading.

    Labels are deliberately about the experience of recall rather than about
    correctness — "hard" and "easy" are answerable honestly, "did you get it
    right" invites self-flattery and corrupts the schedule.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="😵 Не помню", callback_data=ReviewCB(card_id=card_id, grade=1))
    kb.button(text="😬 С трудом", callback_data=ReviewCB(card_id=card_id, grade=2))
    kb.button(text="🙂 Норм", callback_data=ReviewCB(card_id=card_id, grade=3))
    kb.button(text="😎 Легко", callback_data=ReviewCB(card_id=card_id, grade=4))
    kb.adjust(2)
    return kb.as_markup()


def show_answer_kb(card_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Показать ответ", callback_data=ReviewCB(card_id=card_id, grade=0))
    return kb.as_markup()
