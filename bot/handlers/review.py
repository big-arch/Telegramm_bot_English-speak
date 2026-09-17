"""Spaced repetition of words the learner actually met in conversation.

Cards come from real exchanges, not a word list — which is why the answer card
can say where they met the word. That provenance is a small thing that makes
review feel like remembering rather than studying.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DbSession
from sqlalchemy.orm import joinedload

from bot.callbacks import ReviewCB
from bot.db.models import ReviewLog, User, UserCard, Word
from bot.db.repositories import CardRepo
from bot.keyboards.common import review_app_kb, review_kb, show_answer_kb
from bot.services import srs
from bot.texts import REVIEW_EMPTY

logger = logging.getLogger(__name__)
router = Router(name="review")


async def _prompt(message: Message, card: UserCard) -> None:
    await message.answer(
        f"🔁 <b>{card.word.lemma}</b>\n\n<i>Помнишь, что это значит?</i>",
        reply_markup=show_answer_kb(card.id),
    )


@router.message(Command("review"))
async def cmd_review(message: Message, session: DbSession, user: User) -> None:
    """Open the review app, or fall back to the in-chat cards.

    The app is the better experience by some distance — one word at a time,
    two buttons, no message per card clogging the conversation. The chat
    version stays as the fallback for when there is no public HTTPS to serve
    the app from, because a learner should never be told a feature is missing
    for a reason that is about hosting.
    """
    repo = CardRepo(session)
    waiting = len(await repo.study_queue(user.id, limit=1))
    archived = await repo.archived_count(user.id)

    app = review_app_kb()
    if app is not None:
        if not waiting and not archived:
            await message.answer(REVIEW_EMPTY)
            return
        due = await repo.count_due(user.id)
        lines = ["🔁 <b>Повторение</b>", ""]
        lines.append(
            f"Пора повторить: <b>{due}</b>" if due
            else "Срочного ничего — но можно пройтись по всему списку."
        )
        if archived:
            lines.append(f"В архиве: <b>{archived}</b>")
        lines += ["", "<i>Знаю — слово уходит в архив. Не знаю — покажу перевод "
                  "и верну его пораньше.</i>"]
        await message.answer("\n".join(lines), reply_markup=app)
        return

    cards = await repo.due(user.id, limit=srs.DAILY_REVIEW_CAP)
    if not cards:
        await message.answer(REVIEW_EMPTY)
        return

    await message.answer(
        f"К повторению: <b>{len(cards)}</b>\n"
        "<i>Отвечай честно — расписание строится на этом.</i>"
    )
    await _prompt(message, cards[0])


@router.callback_query(ReviewCB.filter())
async def on_review(
    query: CallbackQuery,
    callback_data: ReviewCB,
    session: DbSession,
    user: User,
) -> None:
    await query.answer()
    if not isinstance(query.message, Message):
        return

    card = await session.scalar(
        select(UserCard)
        .where(UserCard.id == callback_data.card_id)
        .options(joinedload(UserCard.word))
    )
    if card is None or card.user_id != user.id:
        return

    word: Word = card.word

    # grade 0 is "show me the answer" — a reveal, not a grade.
    if callback_data.grade == 0:
        body = [f"🔁 <b>{word.lemma}</b>"]
        if word.ipa:
            body.append(f"<code>{word.ipa}</code>")
        if word.translation_ru:
            body.append(word.translation_ru)
        if word.definition_en:
            body.append(f"<i>{word.definition_en}</i>")
        if word.example_en:
            body.append(f"\n«{word.example_en}»")
        body.append("\n<i>Насколько легко вспомнил?</i>")
        await query.message.edit_text("\n".join(body), reply_markup=review_kb(card.id))
        return

    now = datetime.now(timezone.utc)
    elapsed = (
        (now - card.last_reviewed_at).total_seconds() / 86400 if card.last_reviewed_at else 0.0
    )

    # Log before mutating: the log is what an FSRS optimiser would be fitted to,
    # and it needs the state as it was going in.
    session.add(
        ReviewLog(
            user_id=user.id,
            card_id=card.id,
            grade=callback_data.grade,
            elapsed_days=round(elapsed, 3),
            interval_before=card.interval_days,
            ease_before=card.ease,
        )
    )

    updated = srs.review(
        srs.CardState(
            interval_days=card.interval_days,
            ease=card.ease,
            reps=card.reps,
            lapses=card.lapses,
            state=card.state,
        ),
        callback_data.grade,
    )
    card.interval_days = updated.interval_days
    card.ease = updated.ease
    card.reps = updated.reps
    card.lapses = updated.lapses
    card.state = updated.state
    card.last_reviewed_at = now
    card.due_at = srs.due_at(updated, now)
    await session.commit()

    await query.message.edit_text(
        f"✅ <b>{word.lemma}</b> — вернётся через {updated.interval_days} дн."
    )

    remaining = await CardRepo(session).due(user.id, limit=1)
    if remaining:
        await _prompt(query.message, remaining[0])
    else:
        await query.message.answer("Готово на сегодня 👌")
