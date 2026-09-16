# Async SQLAlchemy: patterns and pitfalls

## The repository pattern

Handlers should not contain `select()` statements. Push queries into repositories so business logic is testable and the same query is not reimplemented three times with slightly different filters.

```python
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class CardRepo:
    session: AsyncSession

    async def due_for(self, user_id: int, limit: int = 20) -> list[UserCard]:
        stmt = (
            select(UserCard)
            .where(
                UserCard.user_id == user_id,
                UserCard.state != "new",
                UserCard.due_at <= datetime.now(timezone.utc),
            )
            .order_by(UserCard.due_at)
            .limit(limit)
            .options(joinedload(UserCard.word))
        )
        return list(await self.session.scalars(stmt))

    async def count_due(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(UserCard)
            .where(UserCard.user_id == user_id, UserCard.due_at <= datetime.now(timezone.utc))
        )
        return await self.session.scalar(stmt) or 0
```

The repo takes a session rather than creating one: the middleware owns the session lifetime, the repo just uses it. That keeps one transaction per update.

`joinedload(UserCard.word)` here rather than `selectinload` because it is many-to-one — one JOIN, no extra round trip.

## Scalars, scalar, one, first

- `await session.scalars(stmt)` → a result you iterate for ORM objects. `.first()`, `.one()`, `.all()`.
- `await session.scalar(stmt)` → a single value (counts, aggregates). Returns `None` on no rows.
- `await session.execute(stmt)` → rows as tuples; use when selecting multiple columns.

`.one()` raises if there is not exactly one row — use it where that is genuinely an invariant, so violations surface immediately instead of turning into a silent `None`.

## The MissingGreenlet family

Nearly every `MissingGreenlet: greenlet_spawn has not been called` has one of three causes:

1. **Attribute access after commit** with `expire_on_commit=True` (the default). Fix at the sessionmaker: `async_sessionmaker(engine, expire_on_commit=False)`.
2. **Lazy relationship access.** `user.attempts` outside an eager load. Fix with `selectinload`/`joinedload`, or set `lazy="selectin"` on the relationship if it is always needed.
3. **Using an object after its session closed.** The middleware closes the session at the end of the update; anything passed to a background task must be detached data (a dataclass, a dict, an id), not a live ORM instance.

Setting `lazy="raise"` on relationships during development converts case 2 from a runtime mystery into an immediate, clearly-located error.

## Transactions

The default is a transaction per session, committed explicitly:

```python
async with sessionmaker() as session:
    session.add(attempt)
    card.due_at = next_due
    await session.commit()          # both land together, or neither
```

For an explicit block with automatic commit/rollback:

```python
async with session.begin():
    await repo.record_attempt(...)
    await repo.reschedule(...)
# committed here; rolled back if the block raises
```

Group writes that must be consistent into one transaction. Recording an attempt and updating the card's schedule are one unit of work — committing separately means a crash in between leaves a graded answer with an unchanged due date, and the user reviews the same card forever.

Keep transactions short. Never hold one open across an external call (LLM, TTS, Telegram API): a 30-second API call holding a row lock blocks every other writer touching it.

## Concurrency: two taps on one button

A user double-tapping "Good" can grade the same card twice. Defend at the database level, not with an `if`:

- **Unique constraint** where one row should exist (`uq_user_word`, `payment_charge_id`).
- **`ON CONFLICT DO NOTHING`** for idempotent inserts.
- **`with_for_update()`** when read-modify-write must be serialised:

```python
stmt = select(UserCard).where(UserCard.id == card_id).with_for_update()
card = await session.scalar(stmt)
```

- **Idempotency key** in Redis for anything with an external side effect (a payment grant, a push).

Application-level "check then act" always has a window between the check and the act. On a bot, that window is exactly the double-tap.

## Bulk operations

Inserting a vocabulary list one `session.add()` at a time is thousands of round trips.

```python
await session.execute(insert(Word), [{"lemma": w, "pos": p, "cefr": c} for ...])
```

For updates across many rows, one statement beats a loop:

```python
await session.execute(
    update(UserCard)
    .where(UserCard.user_id == user_id, UserCard.state == "new")
    .values(state="learning")
)
```

Note that bulk statements bypass ORM events and do not update in-memory objects — re-fetch if you need them afterwards.

## Testing

Tests against a real database catch what mocks cannot (constraints, cascades, index behaviour). Use a throwaway Postgres (testcontainers, or a CI service container) rather than SQLite, so the dialect matches production.

```python
import pytest_asyncio


@pytest_asyncio.fixture
async def session(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
```

Faster alternative for large suites: create the schema once, and wrap each test in a transaction that is rolled back afterwards.

Service functions that take a session and plain arguments (rather than a `Message`) are directly testable — which is the main practical reason for the `services/` boundary in the bot skill.

## Performance debugging

1. Turn on `echo=True` locally and run the handler. Count the queries. A repeated near-identical SELECT is N+1.
2. `EXPLAIN ANALYZE` the slow query in `psql`. `Seq Scan` on a large table means a missing or unusable index.
3. Check the index is actually usable: a composite index leads with the equality column; a function applied to a column (`lower(lemma)`) needs an expression index; a `LIKE '%x%'` cannot use a b-tree at all (use `pg_trgm`).
4. Watch pool exhaustion: handlers that await long external calls while holding a session will exhaust `pool_size` and everything appears to hang. Release the session before the slow call, or size the pool for it.

## Timezones

Store `timestamptz` and `datetime.now(timezone.utc)` everywhere. Naive datetimes compare incorrectly against aware ones and raise `TypeError` at the worst moment. Convert to the user's zone only when rendering a message — and remember "today" for a streak is *their* today, not the server's.
