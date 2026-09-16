"""Dialect-aware INSERT ... ON CONFLICT.

SQLite and PostgreSQL both support upserts, but through different constructs,
and the SQLite one does not accept a named `constraint=`. Selecting the right
one here is what lets the same repository code run on a laptop with a file
database and on Supabase in production.
"""

from __future__ import annotations

from bot.config import settings

if settings.is_sqlite:
    from sqlalchemy.dialects.sqlite import insert  # noqa: F401
else:
    from sqlalchemy.dialects.postgresql import insert  # noqa: F401

__all__ = ["insert"]
