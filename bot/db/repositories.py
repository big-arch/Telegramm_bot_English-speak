"""Queries. Handlers should not contain select() statements.

Every repository takes a session rather than creating one — the middleware owns
the session lifetime, which is what keeps one transaction per update.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.db.upsert import insert

from bot.db.models import (
    AudioCache,
    ErrorRecord,
    Session,
    Topic,
    Turn,
    UsageDay,
    User,
    UserCard,
    Word,
)


@dataclass
class UserRepo:
    session: AsyncSession

    async def get_or_create(
        self,
        *,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        language_code: str | None,
    ) -> tuple[User, bool]:
        """Idempotent even against a double-tapped /start.

        A select-then-insert loses that race; the unique index on tg_id plus
        ON CONFLICT wins it at the database level, where it belongs.
        """
        existing = await self.session.scalar(select(User).where(User.tg_id == tg_id))
        if existing is not None:
            existing.username = username
            existing.first_name = first_name
            existing.last_seen_at = datetime.now(timezone.utc)
            existing.is_active = True
            existing.blocked_at = None
            await self.session.commit()
            return existing, False

        stmt = (
            insert(User)
            .values(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                language_code=language_code,
                last_seen_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=[User.tg_id],
                set_={"username": username, "is_active": True, "blocked_at": None},
            )
            .returning(User)
        )
        user = (await self.session.scalars(stmt)).one()
        await self.session.commit()
        return user, True

    async def by_tg_id(self, tg_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.tg_id == tg_id))

    async def mark_blocked(self, tg_id: int) -> None:
        await self.session.execute(
            update(User)
            .where(User.tg_id == tg_id)
            .values(is_active=False, blocked_at=datetime.now(timezone.utc))
        )
        await self.session.commit()


@dataclass
class SessionRepo:
    session: AsyncSession

    async def active_for(self, user_id: int) -> Session | None:
        return await self.session.scalar(
            select(Session)
            .where(Session.user_id == user_id, Session.finished_at.is_(None))
            .order_by(Session.started_at.desc())
            .limit(1)
        )

    async def start(self, *, user_id: int, persona_key: str, topic_id: int | None) -> Session:
        # Close anything dangling so a user can never accumulate open sessions.
        await self.session.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.finished_at.is_(None))
            .values(finished_at=datetime.now(timezone.utc))
        )
        convo = Session(user_id=user_id, persona_key=persona_key, topic_id=topic_id)
        self.session.add(convo)
        await self.session.commit()
        return convo

    async def finish(
        self,
        convo: Session,
        *,
        summary: str | None,
        accuracy: float | None,
        wpm: float | None,
    ) -> None:
        convo.finished_at = datetime.now(timezone.utc)
        convo.summary = summary
        convo.accuracy = accuracy
        convo.words_per_minute = wpm
        await self.session.commit()

    async def history(self, session_id: int, limit: int = 20) -> list[Turn]:
        """Recent turns, oldest first — the shape the Messages API wants."""
        rows = list(
            await self.session.scalars(
                select(Turn)
                .where(Turn.session_id == session_id)
                .order_by(Turn.created_at.desc())
                .limit(limit)
            )
        )
        return list(reversed(rows))


@dataclass
class TurnRepo:
    session: AsyncSession

    async def add(self, turn: Turn) -> Turn:
        self.session.add(turn)
        await self.session.flush()
        return turn

    async def last_voice_turn(self, user_id: int, before_id: int | None = None) -> Turn | None:
        stmt = (
            select(Turn)
            .where(
                Turn.user_id == user_id,
                Turn.modality == "voice",
                Turn.words_per_minute.is_not(None),
            )
            .order_by(Turn.created_at.desc())
        )
        if before_id is not None:
            stmt = stmt.where(Turn.id != before_id)
        return await self.session.scalar(stmt.limit(1))


@dataclass
class ErrorRepo:
    session: AsyncSession

    async def add_many(self, records: list[ErrorRecord]) -> None:
        if not records:
            return
        self.session.add_all(records)
        await self.session.flush()

    async def recent_categories(self, user_id: int, days: int = 14) -> Counter[str]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = await self.session.execute(
            select(ErrorRecord.category, func.count())
            .where(ErrorRecord.user_id == user_id, ErrorRecord.created_at >= since)
            .group_by(ErrorRecord.category)
        )
        return Counter({category: count for category, count in rows.all()})

    async def category_trend(self, user_id: int, category: str, days: int = 28) -> list[int]:
        """Weekly counts, oldest first. The real efficacy metric: is tagged
        feedback actually changing behaviour, or are we correcting into a void?
        """
        now = datetime.now(timezone.utc)
        buckets: list[int] = []
        for week in range(days // 7, 0, -1):
            start = now - timedelta(days=week * 7)
            end = start + timedelta(days=7)
            count = await self.session.scalar(
                select(func.count())
                .select_from(ErrorRecord)
                .where(
                    ErrorRecord.user_id == user_id,
                    ErrorRecord.category == category,
                    ErrorRecord.created_at >= start,
                    ErrorRecord.created_at < end,
                )
            )
            buckets.append(count or 0)
        return buckets


@dataclass
class TopicRepo:
    session: AsyncSession

    async def for_level(self, level: str, limit: int = 8) -> list[Topic]:
        return list(
            await self.session.scalars(
                select(Topic)
                .where(Topic.is_active.is_(True))
                .order_by(func.random())
                .limit(limit)
            )
        )

    async def by_slug(self, slug: str) -> Topic | None:
        return await self.session.scalar(select(Topic).where(Topic.slug == slug))


@dataclass
class CardRepo:
    session: AsyncSession

    async def due(self, user_id: int, limit: int = 20) -> list[UserCard]:
        stmt = (
            select(UserCard)
            .where(
                UserCard.user_id == user_id,
                UserCard.due_at <= datetime.now(timezone.utc),
            )
            .order_by(UserCard.due_at)
            .limit(limit)
            .options(joinedload(UserCard.word))  # many-to-one: one JOIN, no N+1
        )
        return list(await self.session.scalars(stmt))

    async def count_due(self, user_id: int) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(UserCard)
                .where(
                    UserCard.user_id == user_id,
                    UserCard.due_at <= datetime.now(timezone.utc),
                )
            )
            or 0
        )

    async def ensure_word(self, lemma: str, *, cefr: str = "B1") -> Word:
        lemma = lemma.strip().lower()
        stmt = (
            insert(Word)
            .values(lemma=lemma, pos="unknown", cefr=cefr)
            .on_conflict_do_update(
                # index_elements rather than a named constraint: SQLite's upsert
                # does not accept `constraint=`, and this form works on both.
                index_elements=[Word.lemma, Word.pos],
                set_={"lemma": lemma},  # no-op update so RETURNING gives us the row
            )
            .returning(Word)
        )
        return (await self.session.scalars(stmt)).one()

    async def lemmas_for(self, user_id: int) -> set[str]:
        """Every word this learner is already studying.

        The reader needs it to paint saved words red the moment the page opens
        rather than a flicker later — reopening it and seeing a blank page
        looks like the app forgot.
        """
        rows = await self.session.scalars(
            select(Word.lemma).join(UserCard, UserCard.word_id == Word.id).where(
                UserCard.user_id == user_id
            )
        )
        return {lemma.lower() for lemma in rows}

    async def translated(self, lemma: str) -> Word | None:
        """A word already carrying a Russian translation, if the catalogue has
        one. The catalogue is shared, so the second learner to tap "stubborn"
        pays nothing — and neither does the same learner tapping it twice."""
        return await self.session.scalar(
            select(Word).where(
                func.lower(Word.lemma) == lemma.strip().lower(),
                Word.translation_ru.is_not(None),
            )
        )

    async def save_tapped(
        self,
        *,
        user_id: int,
        lemma: str,
        translation_ru: str,
        pos: str = "unknown",
        cefr: str = "B1",
        session_id: int | None = None,
    ) -> tuple[Word, bool]:
        """Record a word the learner pointed at, and return (word, is_new).

        Deliberately idempotent: tapping a word twice must not create a second
        card or reset the schedule of the first. `is_new` is what the reader
        uses to say "saved" rather than "already in your deck", which is the
        difference between feeling productive and feeling ignored.
        """
        lemma = lemma.strip().lower()
        word = await self.ensure_word(lemma, cefr=cefr)

        # First translation wins; later taps must not overwrite a good gloss
        # with a worse one from a different sentence.
        if translation_ru and not word.translation_ru:
            word.translation_ru = translation_ru[:128]

        # `pos` is deliberately NOT written back. It is half of the natural key
        # `ensure_word` upserts on — (lemma, pos) — so rewriting it after the
        # row exists makes the *next* upsert miss, create a second row for the
        # same word, and hand out a second card. A test caught exactly that.
        # The part of speech still reaches the reader, in the response; it just
        # does not get to move the row it lives in.

        stmt = (
            insert(UserCard)
            .values(
                user_id=user_id,
                word_id=word.id,
                due_at=datetime.now(timezone.utc),
                source_session_id=session_id,
            )
            .on_conflict_do_nothing(index_elements=[UserCard.user_id, UserCard.word_id])
        )
        result = await self.session.execute(stmt)
        return word, bool(result.rowcount)

    async def forget(self, *, user_id: int, lemma: str) -> bool:
        """Undo a tap. Mistaking a word is cheap; being unable to take it back
        is what makes people stop tapping."""
        word = await self.session.scalar(
            select(Word).where(func.lower(Word.lemma) == lemma.strip().lower())
        )
        if word is None:
            return False
        result = await self.session.execute(
            delete(UserCard).where(
                UserCard.user_id == user_id, UserCard.word_id == word.id
            )
        )
        return bool(result.rowcount)

    async def add_from_conversation(
        self, *, user_id: int, lemmas: list[str], session_id: int, cefr: str
    ) -> int:
        """Words met in a real conversation make better cards than a word list —
        and the learner can be told where they met them."""
        added = 0
        for lemma in lemmas[:3]:
            if not lemma or not lemma.replace(" ", "").isalpha():
                continue
            word = await self.ensure_word(lemma, cefr=cefr)
            stmt = (
                insert(UserCard)
                .values(
                    user_id=user_id,
                    word_id=word.id,
                    due_at=datetime.now(timezone.utc),
                    source_session_id=session_id,
                )
                .on_conflict_do_nothing(
                    index_elements=[UserCard.user_id, UserCard.word_id]
                )
            )
            result = await self.session.execute(stmt)
            added += result.rowcount or 0
        return added


@dataclass
class UsageRepo:
    session: AsyncSession

    async def bump(
        self,
        *,
        user_id: int,
        day: str,
        voice_turns: int = 0,
        text_turns: int = 0,
        audio_seconds: float = 0.0,
        tts_characters: int = 0,
        llm_in: int = 0,
        llm_out: int = 0,
    ) -> None:
        stmt = (
            insert(UsageDay)
            .values(
                user_id=user_id,
                day=day,
                voice_turns=voice_turns,
                text_turns=text_turns,
                audio_seconds_in=audio_seconds,
                tts_characters=tts_characters,
                llm_input_tokens=llm_in,
                llm_output_tokens=llm_out,
            )
            .on_conflict_do_update(
                index_elements=[UsageDay.user_id, UsageDay.day],
                set_={
                    "voice_turns": UsageDay.voice_turns + voice_turns,
                    "text_turns": UsageDay.text_turns + text_turns,
                    "audio_seconds_in": UsageDay.audio_seconds_in + audio_seconds,
                    "tts_characters": UsageDay.tts_characters + tts_characters,
                    "llm_input_tokens": UsageDay.llm_input_tokens + llm_in,
                    "llm_output_tokens": UsageDay.llm_output_tokens + llm_out,
                },
            )
        )
        await self.session.execute(stmt)

    async def voice_turns_today(self, user_id: int, day: str) -> int:
        return (
            await self.session.scalar(
                select(UsageDay.voice_turns).where(
                    UsageDay.user_id == user_id, UsageDay.day == day
                )
            )
            or 0
        )


@dataclass
class AudioCacheRepo:
    session: AsyncSession

    async def get(self, content_hash: str) -> str | None:
        return await self.session.scalar(
            select(AudioCache.file_id).where(AudioCache.content_hash == content_hash)
        )

    async def put(self, *, content_hash: str, file_id: str, voice_key: str) -> None:
        stmt = (
            insert(AudioCache)
            .values(content_hash=content_hash, file_id=file_id, voice_key=voice_key)
            .on_conflict_do_nothing(index_elements=[AudioCache.content_hash])
        )
        await self.session.execute(stmt)


async def streak_days(session: AsyncSession, user_id: int, tz_name: str = "UTC") -> int:
    """Consecutive days with at least one turn, ending today or yesterday.

    Derived from the event log rather than stored, so it can be recomputed after
    a bug and cannot silently drift.

    Date grouping happens in Python rather than in SQL on purpose: the tidy
    Postgres version uses `timezone()`, which SQLite does not have, and this
    bot is meant to run on both. Bounded to the last 120 days so the row count
    stays small however long someone has been learning.
    """
    since = datetime.now(timezone.utc) - timedelta(days=120)
    rows = await session.scalars(
        select(Turn.created_at)
        .where(Turn.user_id == user_id, Turn.created_at >= since)
        .order_by(Turn.created_at.desc())
    )

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    days: list[date] = []
    seen: set[date] = set()
    for created_at in rows:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        day = created_at.astimezone(tz).date()
        if day not in seen:
            seen.add(day)
            days.append(day)

    if not days:
        return 0

    today = datetime.now(tz).date()
    # Today not yet practised is fine; a two-day gap ends the streak.
    if (today - days[0]).days > 1:
        return 0

    streak = 1
    for previous, current in zip(days, days[1:]):
        if (previous - current).days == 1:
            streak += 1
        else:
            break
    return streak
