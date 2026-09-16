---
name: bot-database
description: Designing and working with the data layer of a Telegram bot — PostgreSQL/Supabase/SQLite schema design, SQLAlchemy 2.0 async ORM, Alembic migrations, repositories, session-per-update, indexing, transactions, Redis for FSM and caching. Use this skill whenever the task involves storing or querying bot data: creating tables or models, writing a migration, connecting to Supabase, fixing slow or locked queries, designing user/progress/vocabulary/SRS schemas, choosing SQLite vs Postgres, adding Redis, or reviewing anything under a `db/`, `models/` or `migrations/` directory — including when the user just says "save the user" or "add a field".
---

# The data layer of a bot

A bot's database is not incidental. It is the product: progress, streaks, spaced repetition, error history and payments all live there, and a schema mistake made in week one is a data migration in month six. This skill covers the decisions that are expensive to reverse, and the async SQLAlchemy idioms that are easy to get subtly wrong.

## Choosing the store

**PostgreSQL by default.** Concurrent writers, real types (`JSONB`, arrays, `timestamptz`), partial and expression indexes, `ON CONFLICT`, and migration tooling that works. A bot is a concurrent application from the first day.

**Supabase is PostgreSQL**, so everything in this skill applies to it unchanged — same SQLAlchemy, same Alembic, same schema design. What differs is connection handling (session-mode pooler vs transaction mode, and the prepared-statement breakage that follows from getting it wrong), connection limits, RLS, and the free-tier pause. This project has a Supabase account, so read `references/supabase.md` before writing the DSN or the first migration.

**SQLite** is defensible for a single-process bot with modest traffic and no ambition to scale. If you use it: enable WAL mode and a busy timeout, or concurrent writes will raise `database is locked` under any real load.

```python
# SQLite only — required, not optional
@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
```

`PRAGMA foreign_keys=ON` matters: SQLite ignores foreign keys by default, so constraints you think you have are decorative.

**Redis** is not an alternative to either. It holds FSM state, throttling counters, hot caches and locks — things that may be lost on restart. Nothing that a user would notice missing belongs only in Redis.

**Never use a JSON file** as a bot's store. Two concurrent updates and it is corrupted.

## SQLAlchemy 2.0, async, typed

The 2.0 style (`Mapped`, `mapped_column`, `select()`) is what to write; the 1.x `Query` API and untyped `Column` declarations are legacy.

```python
from datetime import datetime
from sqlalchemy import BigInteger, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(32))
    language_code: Mapped[str | None] = mapped_column(String(8))
    cefr_level: Mapped[str] = mapped_column(String(2), default="A2")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    attempts: Mapped[list["Attempt"]] = relationship(back_populates="user")
```

Three things that bite specifically in bots:

- **`tg_id` must be `BigInteger`.** Telegram user ids already exceed 32 bits. A plain `Integer` works in testing and overflows on a real user. Channel ids are negative and even larger.
- **Keep a surrogate `id` separate from `tg_id`.** Foreign keys to a platform-owned identifier are painful if you ever support another messenger.
- **`server_default=func.now()`** puts the clock in the database. `default=datetime.now` uses the app server's clock and timezone, which drift. Store UTC (`timestamptz` on Postgres) and convert at the edge.

## Engine and session

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

engine = create_async_engine(
    settings.db_dsn,             # postgresql+asyncpg://user:pass@host/db
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
```

`expire_on_commit=False` is close to mandatory in async code: with the default, touching any attribute after `commit()` triggers a lazy refresh, which in async context raises `MissingGreenlet`. This is the single most common async-SQLAlchemy error and the fix is almost always here rather than at the call site.

`pool_pre_ping=True` survives a database restart and idle connections killed by a proxy.

**Use the async driver.** `psycopg2` is synchronous and will block the whole bot. Postgres → `asyncpg`; SQLite → `aiosqlite`.

## Session per update, via middleware

One session for the lifetime of one update, opened in a middleware and injected into handlers — never a global session, never a session per query.

```python
class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def __call__(self, handler, event, data):
        async with self.sessionmaker() as session:
            data["session"] = session
            return await handler(event, data)
```

A global `AsyncSession` shared across handlers is not concurrency-safe and produces interleaved transactions and `InterfaceError`s that look random. The middleware's `async with` also guarantees rollback on an exception.

Commit explicitly in the handler or service once the unit of work is complete. Autocommit-per-query means a half-finished lesson can be half-persisted.

## Lazy loading is a trap in async

`user.attempts` on a lazily-loaded relationship raises `MissingGreenlet` in async code, because the implicit IO cannot happen there. Load what you need up front:

```python
from sqlalchemy.orm import selectinload

stmt = (
    select(User)
    .where(User.tg_id == tg_id)
    .options(selectinload(User.attempts))
)
user = (await session.scalars(stmt)).first()
```

`selectinload` issues a second `IN` query — the right default for collections. `joinedload` uses one JOIN — better for many-to-one. Setting `lazy="raise"` on relationships turns accidental lazy access into a loud error at development time instead of a production crash.

## Get-or-create without a race

Every bot needs this on `/start`, and the naive select-then-insert loses to a double-tap:

```python
from sqlalchemy.dialects.postgresql import insert

stmt = (
    insert(User)
    .values(tg_id=tg_id, username=username)
    .on_conflict_do_update(
        index_elements=[User.tg_id],
        set_={"username": username, "is_active": True},
    )
    .returning(User)
)
user = (await session.scalars(stmt)).one()
await session.commit()
```

This requires the unique index on `tg_id` that the model above declares. SQLite has the same construct via `sqlalchemy.dialects.sqlite.insert`.

## Migrations: Alembic from commit one

`Base.metadata.create_all()` is acceptable for a throwaway prototype and nothing else — it cannot alter an existing table, so the first schema change loses data or requires manual SQL.

```bash
alembic init -t async migrations       # the async template, not the default
alembic revision --autogenerate -m "add streak fields"
alembic upgrade head
```

Autogenerate is a draft, not an answer. **Always read the generated migration** before applying: it misses column renames (emits drop + add, destroying data), server-default changes, and most constraint edits. Add a `downgrade()` that actually works, and for anything destructive write the data-migration step by hand.

Run `alembic upgrade head` as a deploy step before the new code starts, not from inside the bot process — multiple replicas racing to migrate is a bad time.

Details, async `env.py`, and data-migration patterns: `references/migrations.md`.

## Indexes

Index what you filter and join on, not everything. The ones a learning bot always needs:

```python
__table_args__ = (
    Index("ix_cards_user_due", "user_id", "due_at"),        # the SRS queue query
    Index("ix_attempts_user_created", "user_id", "created_at"),
    UniqueConstraint("user_id", "word_id", name="uq_user_word"),
)
```

A composite index is ordered: `(user_id, due_at)` serves `WHERE user_id = ? AND due_at <= ?` and `WHERE user_id = ?`, but not `WHERE due_at <= ?` alone. Put the equality column first, the range column second.

Verify rather than assume: `EXPLAIN ANALYZE` the query that will run most often. On a table with a million rows, the difference between a sequential scan and an index scan is the difference between a bot that answers and one that times out.

## The N+1 problem, in bot form

Rendering a lesson list and calling `await get_progress(word)` inside the loop issues one query per item. At 20 items that is 20 round trips inside a handler that should take milliseconds. Fetch in one query with a join or an `IN`, then group in Python. Set `echo=True` briefly in development: if one handler prints a screenful of near-identical SELECTs, that is the bug.

## What to store for an English-learning bot

The schema shapes the product, so it is worth designing deliberately rather than growing it field by field. `references/schema-english-bot.md` contains a full worked schema — users, words, user_cards with SRS state, attempts, sessions, errors, subscriptions — with the reasoning behind each table and the queries they are shaped for.

Two principles from it that generalise:

- **Append-only event tables** (`attempts`, `events`) rather than only mutable counters. `streak_days` as a stored integer cannot answer "what did they do last Tuesday", cannot be recomputed after a bug, and cannot feed analytics. Keep the event log and derive the counters (caching them is fine).
- **Separate content from progress.** `words` is shared catalogue data; `user_cards` is one row per user per word holding scheduling state. Mixing them means duplicating content per user and makes content updates impossible.

## Redis: what belongs there

- FSM storage (`RedisStorage.from_url(...)`) — dialog position, recoverable by restarting the flow.
- Throttling counters and distributed locks.
- Caches with a TTL: generated audio `file_id`s, rendered lesson payloads, LLM responses keyed by prompt hash.
- Idempotency keys for payments.

Set a TTL on everything. Redis without expiry is a memory leak with extra steps. And keep Redis out of the critical correctness path: if it is flushed, the bot should degrade, not lose user progress.

## Review checklist

Before shipping a schema or a query change:

- `tg_id` is `BigInteger` and unique-indexed.
- Timestamps are timezone-aware and set by the database.
- Every foreign key has an index (Postgres does not create one automatically).
- Every frequent query has a matching composite index, verified with `EXPLAIN`.
- Money and counts that must not drift are integers (Stars, cents), never floats.
- Deletes are soft (`is_active`, `deleted_at`) wherever history matters; hard deletes only for GDPR-style erasure.
- The migration was read, not just generated, and `downgrade()` works.
- No lazy relationship access in async code paths.
- Sessions come from the middleware and are committed once per unit of work.

## Reference files

- `references/supabase.md` — connecting a bot to Supabase (pooler modes, pool sizing, migrations, RLS, Storage, pgvector, platform gotchas).
- `references/schema-english-bot.md` — full worked schema for a language-learning bot, with the queries each table is shaped for.
- `references/sqlalchemy-async.md` — repository pattern, common async pitfalls, transaction handling, testing with a throwaway database.
- `references/migrations.md` — Alembic async setup, reviewing autogenerate, data migrations, zero-downtime column changes.
