"""Typed callback data.

Telegram caps callback_data at 64 bytes, so these carry ids and short keys —
never text. A payload that needs more than this needs a row in the database and
its id passed here instead.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class LevelCB(CallbackData, prefix="lvl"):
    level: str


class PersonaCB(CallbackData, prefix="prs"):
    key: str


class GoalCB(CallbackData, prefix="goal"):
    key: str


class TopicCB(CallbackData, prefix="tpc"):
    topic_id: int


class StyleCB(CallbackData, prefix="sty"):
    style: str


class ReviewCB(CallbackData, prefix="rev"):
    card_id: int
    grade: int


class SettingsCB(CallbackData, prefix="set"):
    section: str


class RetryCB(CallbackData, prefix="rty"):
    """Used by the hint-then-reveal correction flow."""

    error_id: int
    action: str  # show | skip
