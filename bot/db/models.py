"""SpeakOut schema.

Two principles shape this, both from hard experience with learning products:

1. Content and progress are separate. `words` and `topics` are a shared
   catalogue; `user_cards` and `turns` are per user. That is what lets you fix a
   typo in a definition without touching anyone's history.

2. Event tables are append-only. `turns` and `error_records` are never updated.
   Streaks, accuracy and "you improved 20% this week" are all derived from them,
   so any of those can be recomputed after a bug — and questions you haven't
   thought of yet remain answerable.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Telegram ids exceed 32 bits — Integer overflows on real users.
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(32))
    first_name: Mapped[str | None] = mapped_column(String(64))
    language_code: Mapped[str | None] = mapped_column(String(8))

    # Receptive runs roughly a band ahead of productive; a single level column
    # forces you to either bore them with input or overface them with tasks.
    productive_level: Mapped[str] = mapped_column(String(2), default="A2")
    receptive_level: Mapped[str] = mapped_column(String(2), default="A2")
    level_score: Mapped[float] = mapped_column(Float, default=25.0)  # 0-100, continuous

    persona_key: Mapped[str] = mapped_column(String(16), default="emma")
    correction_style: Mapped[str] = mapped_column(String(10), default="balanced")
    goal: Mapped[str | None] = mapped_column(String(32))  # travel, work, exams, general

    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    reminder_hour: Mapped[int | None] = mapped_column(SmallInteger)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # A rolling, model-written summary of who this learner is and what they have
    # talked about. This is the single field that makes conversations stop
    # feeling like they reset every time — the #1 complaint about every
    # competitor in this space.
    memory_summary: Mapped[str | None] = mapped_column(Text)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Topic(Base):
    """Conversation topics. Shared catalogue, seeded from data/topics.py."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    title_en: Mapped[str] = mapped_column(String(96))
    title_ru: Mapped[str] = mapped_column(String(96))
    emoji: Mapped[str] = mapped_column(String(8), default="💬")
    cefr_min: Mapped[str] = mapped_column(String(2), default="A2")
    cefr_max: Mapped[str] = mapped_column(String(2), default="C1")
    category: Mapped[str] = mapped_column(String(24), default="general")
    # What the tutor should try to elicit, and how the conversation should open.
    opening_line: Mapped[str] = mapped_column(Text)
    goal_prompt: Mapped[str] = mapped_column(Text)
    target_lexis: Mapped[str | None] = mapped_column(Text)  # comma-separated lemmas
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(Base):
    """One conversation from /talk to /finish."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    persona_key: Mapped[str] = mapped_column(String(16))

    started_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The tutor's first line. Kept so it can be replayed into the model's
    # history — without it the model does not know what question the learner's
    # first answer is answering.
    opening_line: Mapped[str | None] = mapped_column(Text)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    voice_turn_count: Mapped[int] = mapped_column(Integer, default=0)

    # Filled at /finish by the debrief step.
    summary: Mapped[str | None] = mapped_column(Text)
    accuracy: Mapped[float | None] = mapped_column(Float)
    words_per_minute: Mapped[float | None] = mapped_column(Float)

    user: Mapped["User"] = relationship(back_populates="sessions")
    turns: Mapped[list["Turn"]] = relationship(back_populates="session")

    __table_args__ = (Index("ix_sessions_user_started", "user_id", "started_at"),)


class Turn(Base):
    """One exchange. Append-only.

    Stores the learner's side (transcript + measured fluency) and the tutor's
    side (reply text). Everything the product claims about progress is derived
    from this table.
    """

    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    modality: Mapped[str] = mapped_column(String(8))  # voice | text | photo
    user_text: Mapped[str] = mapped_column(Text)
    assistant_text: Mapped[str] = mapped_column(Text)

    # Telegram's id for a photo the learner sent. Kept so it can be shown back
    # to them later — "remember this? tell me about it again" is a genuinely
    # good revision prompt, and re-sending by file_id costs nothing.
    image_file_id: Mapped[str | None] = mapped_column(String(160))

    # Fluency, measured from Whisper word timestamps. Nulls for text turns.
    audio_seconds: Mapped[float | None] = mapped_column(Float)
    word_count: Mapped[int | None] = mapped_column(Integer)
    words_per_minute: Mapped[float | None] = mapped_column(Float)
    articulation_wpm: Mapped[float | None] = mapped_column(Float)
    pause_ratio: Mapped[float | None] = mapped_column(Float)
    mid_clause_pauses: Mapped[int | None] = mapped_column(Integer)
    mean_run_words: Mapped[float | None] = mapped_column(Float)

    # Assessor output, kept for recomputation and analytics.
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_level: Mapped[str | None] = mapped_column(String(2))
    lexical_range: Mapped[int | None] = mapped_column(SmallInteger)
    grammatical_range: Mapped[int | None] = mapped_column(SmallInteger)
    accuracy_score: Mapped[int | None] = mapped_column(SmallInteger)

    created_at: Mapped[datetime] = _ts()

    session: Mapped["Session"] = relationship(back_populates="turns")

    __table_args__ = (Index("ix_turns_user_created", "user_id", "created_at"),)


class ErrorRecord(Base):
    """A tagged correction. The most valuable data this product accumulates."""

    __tablename__ = "error_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[int | None] = mapped_column(ForeignKey("turns.id", ondelete="CASCADE"))

    category: Mapped[str] = mapped_column(String(24), index=True)
    severity: Mapped[str] = mapped_column(String(12))  # blocking | noticeable | minor
    original_span: Mapped[str] = mapped_column(Text)
    correction: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)

    # Set when the learner has been shown this and practised it.
    surfaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_errors_user_cat_time", "user_id", "category", "created_at"),)


class Word(Base):
    """Shared vocabulary catalogue."""

    __tablename__ = "words"

    id: Mapped[int] = mapped_column(primary_key=True)
    lemma: Mapped[str] = mapped_column(String(64), index=True)
    pos: Mapped[str] = mapped_column(String(16), default="unknown")
    cefr: Mapped[str] = mapped_column(String(2), index=True, default="B1")
    translation_ru: Mapped[str | None] = mapped_column(String(128))
    definition_en: Mapped[str | None] = mapped_column(Text)
    example_en: Mapped[str | None] = mapped_column(Text)
    ipa: Mapped[str | None] = mapped_column(String(64))
    audio_file_id: Mapped[str | None] = mapped_column(String(160))

    # record (noun) and record (verb) differ in stress, level and meaning.
    __table_args__ = (UniqueConstraint("lemma", "pos", name="uq_word_lemma_pos"),)


class UserCard(Base):
    """Per-user spaced-repetition state for one word. SM-2 for now.

    The column names are deliberately SM-2's (`ease`, `interval_days`). If you
    later move to FSRS, add `stability`/`difficulty` alongside rather than
    renaming — `review_log` below carries what the FSRS optimiser needs.
    """

    __tablename__ = "user_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"))

    state: Mapped[str] = mapped_column(String(12), default="new")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Where the word came from: a conversation the learner actually had beats a
    # word list, and is worth showing them ("you met this talking to Jake").
    source_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )

    # How it got here: "conversation" when the assessor picked it out of a turn
    # by itself, "tapped" when the learner pointed at it in the reader. Both
    # are studied the same way, but only the second may be painted red — the
    # reader marking words nobody chose looks like a rendering fault, which is
    # exactly how it was reported.
    origin: Mapped[str] = mapped_column(String(16), default="conversation")

    # Eager-loadable from the queue query. Lazy access would raise
    # MissingGreenlet in async code, so callers always joinedload this.
    word: Mapped["Word"] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("user_id", "word_id", name="uq_user_word"),
        # The hottest query in the product: the due queue.
        Index("ix_cards_due_queue", "user_id", "state", "due_at"),
    )


class ReviewLog(Base):
    """Append-only review history. Feeds FSRS parameter fitting later."""

    __tablename__ = "review_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    card_id: Mapped[int] = mapped_column(ForeignKey("user_cards.id", ondelete="CASCADE"))

    grade: Mapped[int] = mapped_column(SmallInteger)  # 1 again, 2 hard, 3 good, 4 easy
    elapsed_days: Mapped[float] = mapped_column(Float, default=0.0)
    interval_before: Mapped[int] = mapped_column(Integer, default=0)
    ease_before: Mapped[float] = mapped_column(Float, default=2.5)
    response_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts()


class AudioCache(Base):
    """content hash -> Telegram file_id.

    Re-sending by file_id is free and instant. Without this, every repeated
    phrase costs another TTS call plus an upload — for a vocabulary bot that is
    the difference between a trivial bill and a large one.
    """

    __tablename__ = "audio_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_id: Mapped[str] = mapped_column(String(160))
    voice_key: Mapped[str] = mapped_column(String(48))
    created_at: Mapped[datetime] = _ts()


class UsageDay(Base):
    """Per-user daily counters. Drives free limits and cost monitoring.

    Kept as a small mutable aggregate on purpose: it is a counter, not history.
    `turns` remains the source of truth.
    """

    __tablename__ = "usage_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD in the user's timezone

    voice_turns: Mapped[int] = mapped_column(Integer, default=0)
    text_turns: Mapped[int] = mapped_column(Integer, default=0)
    audio_seconds_in: Mapped[float] = mapped_column(Float, default=0.0)
    tts_characters: Mapped[int] = mapped_column(Integer, default=0)
    llm_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_usage_user_day"),)
