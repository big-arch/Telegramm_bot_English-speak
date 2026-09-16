"""Engine and session factory.

Runs on SQLite (free, zero setup, single process) or PostgreSQL/Supabase
(concurrent, scalable) from the same code.

Supabase note: use the SESSION-mode pooler (port 5432). Transaction mode (6543)
breaks asyncpg's prepared-statement cache and produces intermittent
`prepared statement ... does not exist` errors that are miserable to debug.
Keep the pool small — Supabase caps total connections per project, and that
budget is shared with the dashboard and any psql session you have open.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from bot.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    if settings.is_sqlite:
        # Make sure the directory exists before SQLite tries to create the file.
        path = settings.db_dsn.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        engine = create_async_engine(settings.db_dsn, echo=False)

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            # WAL and a busy timeout are not optional: without them concurrent
            # writes raise "database is locked" under any real load.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            # SQLite ignores foreign keys by default, so the constraints you
            # think you have are decorative until this is on.
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    return create_async_engine(
        settings.db_dsn,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        echo=False,
    )


engine = _make_engine()

sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,  # required in async code — see the bot-database skill
)
