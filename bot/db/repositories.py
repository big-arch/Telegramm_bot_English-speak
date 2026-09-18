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
                # Archived words are out of rotation until the learner resets
                # the archive; they keep their due date, so without this they
                # would keep coming back through every other queue.
                UserCard.state != "archived",
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
                    UserCard.state != "archived",
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

    async def lemmas_for(self, user_id: int, *, origin: str | None = None) -> set[str]:
        """Words this learner is studying, optionally only those they chose.

        The reader passes origin="tapped" so that red means "I picked this".
        Marking every word in the deck also marks the ones the assessor
        collected by itself, and a reader lighting up words nobody chose reads
        as the text underlining itself — which is how it was reported.
        """
        stmt = select(Word.lemma).join(UserCard, UserCard.word_id == Word.id).where(
            UserCard.user_id == user_id
        )
        if origin is not None:
            stmt = stmt.where(UserCard.origin == origin)
        return {lemma.lower() for lemma in await self.session.scalars(stmt)}

    async def study_queue(self, user_id: int, limit: int = 40) -> list[tuple[UserCard, Word]]:
        """What to show in the review app: everything not archived, due first.

        Deliberately not limited to cards that are due. Someone who opens the
        app wanting to study should always find something — being told "come
        back tomorrow" is how a habit dies in its first week. Due cards lead
        because they are the ones about to be forgotten.
        """
        rows = await self.session.execute(
            select(UserCard, Word)
            .join(Word, UserCard.word_id == Word.id)
            .where(UserCard.user_id == user_id, UserCard.state != "archived")
            .order_by(UserCard.due_at)
            .limit(limit)
        )
        return [(card, word) for card, word in rows.all()]

    async def archive(self, *, user_id: int, card_id: int) -> bool:
        """"I know this one." Out of rotation until the archive is reset.

        Kept rather than deleted: a word someone was confident about six months
        ago is exactly the kind of thing worth handing back later, and deleting
        it throws away the only evidence that they ever met it.
        """
        result = await self.session.execute(
            update(UserCard)
            .where(UserCard.id == card_id, UserCard.user_id == user_id)
            .values(state="archived", last_reviewed_at=datetime.now(timezone.utc))
        )
        return bool(result.rowcount)

    async def archived_count(self, user_id: int) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(UserCard)
                .where(UserCard.user_id == user_id, UserCard.state == "archived")
            )
        ) or 0

    async def reset_archive(self, user_id: int) -> int:
        """Bring every archived word back, due now.

        The schedule is reset with it. Whatever interval a card had earned
        before it was archived is not evidence about a word the learner has
        deliberately asked to see again.
        """
        result = await self.session.execute(
            update(UserCard)
            .where(UserCard.user_id == user_id, UserCard.state == "archived")
            .values(
                state="new",
                due_at=datetime.now(timezone.utc),
                interval_days=0,
                ease=2.5,
            )
        )
        return result.rowcount or 0

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
                origin="tapped",
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


@dataclass
class StatsRepo:
    """Numbers about the product, for whoever built it.

    Deliberately aggregate only. Nothing here returns a message, a transcript
    or a name — the operator needs to know whether the thing works, not what
    anyone said to it, and building the second while asking for the first is
    how a learning product quietly becomes surveillance.
    """

    session: AsyncSession

    async def _count(self, stmt) -> int:
        return (await self.session.scalar(stmt)) or 0

    async def overview(self) -> dict:
        now = datetime.now(timezone.utc)
        day = now - timedelta(days=1)
        week = now - timedelta(days=7)
        month = now - timedelta(days=30)

        users = select(func.count()).select_from(User)
        total = await self._count(users)

        # "Opened the app" is people who pressed /start. Everything after this
        # is about how many of them the product actually kept.
        new_today = await self._count(users.where(User.created_at >= day))
        new_week = await self._count(users.where(User.created_at >= week))

        active_today = await self._count(users.where(User.last_seen_at >= day))
        active_week = await self._count(users.where(User.last_seen_at >= week))
        active_month = await self._count(users.where(User.last_seen_at >= month))

        blocked = await self._count(users.where(User.is_active.is_(False)))

        # The only number that says whether this is a product or a demo: people
        # who said something, not people who arrived and looked around.
        spoke = await self._count(
            select(func.count(func.distinct(Turn.user_id))).select_from(Turn)
        )

        # ...and of those, the ones who came back on a different day. Second-day
        # return is the number every consumer product lives or dies on, and it
        # is invisible in a total-installs figure.
        days_per_user = (
            select(Turn.user_id, func.count(func.distinct(func.date(Turn.created_at))).label("days"))
            .group_by(Turn.user_id)
            .subquery()
        )
        returned = await self._count(
            select(func.count()).select_from(days_per_user).where(days_per_user.c.days >= 2)
        )

        conversations = await self._count(select(func.count()).select_from(Session))
        finished = await self._count(
            select(func.count()).select_from(Session).where(Session.finished_at.is_not(None))
        )

        turns = select(func.count()).select_from(Turn)
        voice = await self._count(turns.where(Turn.modality == "voice"))
        text = await self._count(turns.where(Turn.modality == "text"))
        photos = await self._count(turns.where(Turn.modality == "photo"))

        opens = await self.session.execute(
            select(
                func.coalesce(func.sum(UsageDay.reader_opens), 0),
                func.coalesce(func.sum(UsageDay.review_opens), 0),
            )
        )
        reader_opens, review_opens = opens.one()

        cards = await self._count(select(func.count()).select_from(UserCard))
        tapped = await self._count(
            select(func.count()).select_from(UserCard).where(UserCard.origin == "tapped")
        )

        tokens = await self.session.execute(
            select(
                func.coalesce(func.sum(UsageDay.llm_input_tokens), 0),
                func.coalesce(func.sum(UsageDay.llm_output_tokens), 0),
                func.coalesce(func.sum(UsageDay.audio_seconds_in), 0.0),
            )
        )
        llm_in, llm_out, audio_seconds = tokens.one()

        return {
            "total": total,
            "new_today": new_today,
            "new_week": new_week,
            "active_today": active_today,
            "active_week": active_week,
            "active_month": active_month,
            "blocked": blocked,
            "spoke": spoke,
            "returned": returned,
            "conversations": conversations,
            "finished": finished,
            "voice": voice,
            "text": text,
            "photos": photos,
            "reader_opens": int(reader_opens),
            "review_opens": int(review_opens),
            "cards": cards,
            "tapped": tapped,
            "llm_in": int(llm_in),
            "llm_out": int(llm_out),
            "audio_minutes": float(audio_seconds) / 60.0,
        }

    async def funnel(self) -> list[tuple[str, int]]:
        """Where people stop, in order.

        More useful than any single total: a step that loses most of the
        people who reached it is a bug with a location.
        """
        users = select(func.count()).select_from(User)
        return [
            ("Нажали /start", await self._count(users)),
            ("Выбрали уровень", await self._count(users.where(User.goal.is_not(None)))),
            (
                "Сказали хоть что-то",
                await self._count(
                    select(func.count(func.distinct(Turn.user_id))).select_from(Turn)
                ),
            ),
            (
                "Записали голосовое",
                await self._count(
                    select(func.count(func.distinct(Turn.user_id)))
                    .select_from(Turn)
                    .where(Turn.modality == "voice")
                ),
            ),
            (
                "Дошли до /finish",
                await self._count(
                    select(func.count(func.distinct(Session.user_id)))
                    .select_from(Session)
                    .where(Session.finished_at.is_not(None))
                ),
            ),
            (
                "Учат слова",
                await self._count(
                    select(func.count(func.distinct(UserCard.user_id))).select_from(UserCard)
                ),
            ),
        ]

    async def daily(self, days: int = 14) -> list[tuple[str, int, int]]:
        """(day, people who spoke, turns) — newest last, for a small chart."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = await self.session.execute(
            select(
                func.date(Turn.created_at).label("day"),
                func.count(func.distinct(Turn.user_id)),
                func.count(),
            )
            .where(Turn.created_at >= since)
            .group_by("day")
            .order_by("day")
        )
        return [(str(day), people, count) for day, people, count in rows.all()]
