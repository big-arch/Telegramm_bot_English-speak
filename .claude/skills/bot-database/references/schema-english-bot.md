# A worked schema for an English-learning bot

This is a starting point that has survived contact with the product questions such bots eventually face: "what's my streak", "which words am I bad at", "what should I review now", "did my speaking improve", "who's due for a reminder", "did this user pay".

## The shape

```
users ──┬── user_cards ──── words
        ├── attempts ────── words
        ├── sessions
        ├── errors
        └── subscriptions
```

Content (`words`, and later `lessons`, `dialogues`) is shared. Progress (`user_cards`, `attempts`) is per user. Keeping that boundary clean is what lets you fix a typo in a word definition without touching anyone's progress.

## users

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(32))
    first_name: Mapped[str | None] = mapped_column(String(64))
    language_code: Mapped[str | None] = mapped_column(String(8))

    cefr_level: Mapped[str] = mapped_column(String(2), default="A2")
    daily_goal: Mapped[int] = mapped_column(default=10)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    reminder_hour: Mapped[int | None] = mapped_column(SmallInteger)

    is_active: Mapped[bool] = mapped_column(default=True)
    blocked_at: Mapped[datetime | None] = mapped_column(timezone=True)
    created_at: Mapped[datetime] = mapped_column(timezone=True, server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(timezone=True)
```

`timezone` and `reminder_hour` are the pair that makes reminders work. Storing "send at 09:00" globally means a Vladivostok user gets pinged at night; store the user's IANA zone and compute the UTC moment. Telegram does not give you the timezone — ask, or infer from `language_code` as a first guess and let them correct it.

`blocked_at` is set when a send raises `TelegramForbiddenError`. Without it you keep broadcasting into the void and your "active users" metric is fiction.

Note there is no `streak_days` column here. See **Derived counters** below.

## words — the shared catalogue

```python
class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(primary_key=True)
    lemma: Mapped[str] = mapped_column(String(64), index=True)
    pos: Mapped[str] = mapped_column(String(16))            # noun, verb, adj…
    cefr: Mapped[str] = mapped_column(String(2), index=True) # A1…C2
    frequency_rank: Mapped[int | None]                       # corpus rank
    ipa: Mapped[str | None] = mapped_column(String(64))
    translation_ru: Mapped[str | None] = mapped_column(String(128))
    definition_en: Mapped[str | None] = mapped_column(Text)
    example_en: Mapped[str | None] = mapped_column(Text)
    audio_file_id: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (UniqueConstraint("lemma", "pos", name="uq_word_lemma_pos"),)
```

`(lemma, pos)` unique, not `lemma` alone: *record* the noun and *record* the verb differ in pronunciation, CEFR level and meaning, and a learner needs them as separate cards.

`cefr` and `frequency_rank` are what let you serve level-appropriate content — the pedagogical reasoning is in the `english-tutor-linguistics` skill.

`audio_file_id` is the Telegram `file_id` of the generated pronunciation. Cache it here and a TTS call becomes a free re-send.

## user_cards — scheduling state

One row per (user, word). This is where spaced repetition lives.

```python
class UserCard(Base):
    __tablename__ = "user_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), index=True)

    state: Mapped[str] = mapped_column(String(12), default="new")  # new/learning/review/relearning
    due_at: Mapped[datetime] = mapped_column(timezone=True, index=True)
    stability: Mapped[float] = mapped_column(default=0.0)
    difficulty: Mapped[float] = mapped_column(default=5.0)
    reps: Mapped[int] = mapped_column(default=0)
    lapses: Mapped[int] = mapped_column(default=0)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(timezone=True)

    __table_args__ = (
        UniqueConstraint("user_id", "word_id", name="uq_user_word"),
        Index("ix_cards_due_queue", "user_id", "state", "due_at"),
    )
```

`ix_cards_due_queue` exists for the single hottest query in the product:

```sql
SELECT * FROM user_cards
WHERE user_id = :uid AND state <> 'new' AND due_at <= now()
ORDER BY due_at
LIMIT 20;
```

Every session starts with it. Without the composite index it is a full scan of the user's whole vocabulary on every `/study`.

`stability` and `difficulty` are FSRS's memory-model parameters; if the project uses SM-2 instead, replace them with `ease_factor` and `interval_days`. Either way, **keep the scheduler's state in named columns rather than a JSON blob** — you will want to query it ("how many mature cards does this user have", "which words does everyone find hard") and JSON makes that awkward and unindexed.

## attempts — the append-only event log

```python
class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    word_id: Mapped[int | None] = mapped_column(ForeignKey("words.id", ondelete="SET NULL"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))

    exercise_type: Mapped[str] = mapped_column(String(24))   # recall, listening, speaking, cloze
    grade: Mapped[int] = mapped_column(SmallInteger)          # 1..4 (again/hard/good/easy)
    is_correct: Mapped[bool]
    response_ms: Mapped[int | None]
    user_answer: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(timezone=True, server_default=func.now(), index=True)

    __table_args__ = (Index("ix_attempts_user_time", "user_id", "created_at"),)
```

This table is never updated, only inserted into. That is what makes it trustworthy: streaks, daily goals, retention curves, "your accuracy this week", and any future analytics are all derivable from it, and any of them can be recomputed after a bug. A product that stores only the current counters can never answer a question it did not anticipate.

`response_ms` is worth capturing even if unused at first — response latency is a strong signal of recall strength and feeds better scheduling later.

## sessions — one practice run

```python
class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))            # review, lesson, free_talk
    started_at: Mapped[datetime] = mapped_column(timezone=True, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(timezone=True)
    cards_done: Mapped[int] = mapped_column(default=0)
    accuracy: Mapped[float | None]
```

Gives you completion rate (sessions started vs finished), which is the honest engagement metric — message counts flatter you.

## errors — what the learner actually gets wrong

```python
class ErrorRecord(Base):
    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"))

    category: Mapped[str] = mapped_column(String(32), index=True)  # article, tense, preposition…
    original: Mapped[str] = mapped_column(Text)
    correction: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(timezone=True, server_default=func.now())
```

A tagged error history is the difference between a bot that corrects and a bot that teaches: it lets you say "articles are still your weak spot — three of your last ten sentences" and generate targeted practice. The taxonomy to use for `category` is in the `english-tutor-linguistics` skill.

## subscriptions and payments

```python
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(24))
    starts_at: Mapped[datetime] = mapped_column(timezone=True)
    expires_at: Mapped[datetime] = mapped_column(timezone=True, index=True)
    payment_charge_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    refunded_at: Mapped[datetime | None] = mapped_column(timezone=True)
```

`payment_charge_id` unique gives you idempotency for free: a retried `successful_payment` update cannot grant two months. Keep `refunded_at` because Telegram Stars payments are refundable for 21 days and access must be revocable.

Amounts, if stored, are integers in the smallest unit (Stars, or cents). Floats and money do not mix.

## Derived counters

`streak_days`, `total_words_learned`, `accuracy_7d` are all functions of `attempts`. Compute them:

```sql
-- current streak: count consecutive days ending today with at least one attempt
WITH days AS (
  SELECT DISTINCT date_trunc('day', created_at AT TIME ZONE :tz) AS d
  FROM attempts WHERE user_id = :uid
)
SELECT count(*) FROM days
WHERE d > (
  SELECT coalesce(max(d), '-infinity') FROM days d2
  WHERE NOT EXISTS (SELECT 1 FROM days d3 WHERE d3.d = d2.d + interval '1 day')
    AND d2.d < current_date
);
```

If that gets slow, cache the result in Redis with a TTL until midnight in the user's timezone, or denormalise into `users` *as a cache* — updated from the event log, never as the source of truth. The distinction matters: a cache can be rebuilt after a bug, a source of truth cannot.

## Growth paths

- **Lessons/dialogues**: a `lessons` table plus `user_lesson_progress`, same content/progress split.
- **Multiple languages**: add `language` to `words` and to `user_cards`' uniqueness, not a new set of tables.
- **A/B experiments**: an `experiment_assignments` table keyed by user, assigned once and stored — never recomputed from a hash at read time, or a deploy silently reshuffles cohorts.
- **Analytics volume**: when `attempts` passes tens of millions, partition by month rather than adding indexes.
