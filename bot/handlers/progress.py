"""Progress, reported honestly.

Total messages, words "seen" and time in app are vanity metrics — a bot can
maximise all three while teaching nothing. What is shown here is what actually
correlates with learning: days active, speech that got faster, and whether a
tagged error category is going down.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from bot.db.models import Turn, User
from bot.db.repositories import CardRepo, ErrorRepo, streak_days
from bot.services.feedback import CATEGORY_RU
from bot.texts import progress_card

router = Router(name="progress")


@router.message(Command("progress"))
async def cmd_progress(message: Message, session: DbSession, user: User) -> None:
    total_turns = (
        await session.scalar(
            select(func.count()).select_from(Turn).where(Turn.user_id == user.id)
        )
        or 0
    )
    voice_seconds = (
        await session.scalar(
            select(func.coalesce(func.sum(Turn.audio_seconds), 0.0)).where(
                Turn.user_id == user.id
            )
        )
        or 0.0
    )
    avg_wpm = await session.scalar(
        select(func.avg(Turn.words_per_minute)).where(
            Turn.user_id == user.id, Turn.words_per_minute.is_not(None)
        )
    )

    recent = await ErrorRepo(session).recent_categories(user.id, days=14)
    top = recent.most_common(1)
    top_error = (CATEGORY_RU.get(top[0][0], top[0][0]), top[0][1]) if top else None

    await message.answer(
        progress_card(
            streak=await streak_days(session, user.id, user.timezone),
            total_turns=total_turns,
            voice_minutes=voice_seconds / 60,
            wpm=float(avg_wpm) if avg_wpm else None,
            top_error=top_error,
            due_cards=await CardRepo(session).count_due(user.id),
            level=user.productive_level,
        )
    )


@router.message(Command("mistakes"))
async def cmd_mistakes(message: Message, session: DbSession, user: User) -> None:
    """Is the feedback actually changing behaviour, or are we correcting into a void?"""
    repo = ErrorRepo(session)
    recent = await repo.recent_categories(user.id, days=28)
    if not recent:
        await message.answer("Пока не набралось ошибок для анализа. Поговори немного 🙂")
        return

    lines = ["📉 <b>Твои ошибки за 4 недели</b>", ""]
    for category, count in recent.most_common(5):
        trend = await repo.category_trend(user.id, category, days=28)
        spark = " ".join(str(n) for n in trend)
        direction = ""
        if len(trend) >= 2:
            if trend[-1] < trend[0]:
                direction = " ↓ реже"
            elif trend[-1] > trend[0]:
                direction = " ↑ чаще"
        lines.append(
            f"<b>{CATEGORY_RU.get(category, category)}</b> — {count}{direction}\n"
            f"<code>по неделям: {spark}</code>"
        )

    lines += ["", "<i>Это не приговор. Это то, что я специально подкладываю тебе в разговорах.</i>"]
    await message.answer("\n\n".join(lines))
