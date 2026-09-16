"""Engine and session factory.

Supabase note: use the SESSION-mode pooler (port 5432). Transaction mode (6543)
breaks asyncpg's prepared-statement cache and produces intermittent
`prepared statement ... does not exist` errors that are miserable to debug.
Keep the pool small — Supabase caps total connections per project, and that
budget is shared with the dashboard and any psql session you have open.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from bot.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.db_dsn,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    echo=False,
)

sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,  # required in async code — see bot-database skill
)
