"""Check the database configuration and say plainly what is wrong.

"Failed deploy" plus a SQLAlchemy traceback tells a person nothing they can
act on. This runs before migrations and turns the four mistakes that actually
happen into one readable line each — with the connection string echoed back
with its password masked, so a placeholder left unreplaced is visible at a
glance.

    python -m scripts.doctor

Exits non-zero when the database cannot be used.
"""

from __future__ import annotations

import asyncio
import re
import sys

from bot.config import settings

PLACEHOLDERS = ("[YOUR-PASSWORD]", "YOUR-PASSWORD", "<password>", "your-password")

# Fragments that only appear in a documentation example. Copying the whole
# example line and changing just the password produces a string that is
# perfectly well-formed and points at somebody else's project — the database
# then rejects the password, and the error blames the password rather than the
# address. Naming it here is the only way that mistake becomes obvious.
EXAMPLE_MARKERS = (
    "abcdefgh",
    "project-ref",
    "<ref>",
    "region",
    "твойпароль",
    "example.com",
    "<pw>",
)


def mask(dsn: str) -> str:
    """Hide the password, keep everything else readable."""
    return re.sub(r"(://[^:/@]+:)([^@]*)(@)", r"\1***\3", dsn)


def problems(dsn: str) -> list[str]:
    found: list[str] = []
    lowered = dsn.lower()

    if any(p.lower() in lowered for p in PLACEHOLDERS):
        found.append(
            "The password placeholder was never replaced. Supabase gives you the "
            "string with [YOUR-PASSWORD] in it — swap that, brackets included, for "
            "the database password you chose when creating the project."
        )

    if lowered.startswith("postgresql://") or lowered.startswith("postgres://"):
        found.append(
            "The scheme is missing its driver. Change the beginning of the string "
            "from 'postgresql://' to 'postgresql+asyncpg://' — the bot talks to "
            "Postgres asynchronously and cannot use the default driver."
        )

    leaked = [m for m in EXAMPLE_MARKERS if m in lowered]
    if leaked:
        found.append(
            f"This looks like the documentation example, not your own string "
            f"(it still contains {', '.join(repr(m) for m in leaked)}). Open your "
            "Supabase project -> Project Settings -> Database -> Connection string, "
            "switch the selector to 'Session pooler', and copy THAT line. The "
            "username must contain your project's reference and the host must name "
            "your project's region."
        )

    if ":6543/" in dsn:
        found.append(
            "Port 6543 is Supabase's TRANSACTION pooler, which breaks this bot in "
            "ways that are very hard to diagnose. In Supabase, switch the "
            "connection-string selector to 'Session pooler' and copy again — that "
            "one uses port 5432."
        )

    # A password with these characters silently truncates or corrupts the URL.
    #
    # Split on the LAST '@' rather than the first: a password containing '@' is
    # precisely the case worth catching, and anchoring on the first one would
    # read half the password and find nothing wrong with it.
    password = _password_of(dsn)
    if password:
        bad = {c for c in password if c in "@#/?:[] "}
        if bad:
            found.append(
                f"The password contains {' '.join(sorted(bad))}, which breaks the "
                "connection string. Change the database password in Supabase to "
                "letters and digits only, then update DB_DSN."
            )

    return found


def _password_of(dsn: str) -> str:
    if "://" not in dsn:
        return ""
    after_scheme = dsn.split("://", 1)[1]
    if "@" not in after_scheme:
        return ""
    userinfo, _, _host = after_scheme.rpartition("@")
    _user, sep, password = userinfo.partition(":")
    return password if sep else ""


async def try_connect() -> str | None:
    """Returns an error description, or None when the connection works."""
    from sqlalchemy import text

    from bot.db.base import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:  # noqa: BLE001 — every failure here is reportable
        return f"{type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()


def main() -> int:
    dsn = settings.db_dsn
    print(f"    database: {mask(dsn)}")

    if settings.is_sqlite:
        print("    NOTE: running on a local file. On hosting with ephemeral disk")
        print("          every redeploy wipes all user progress. Set DB_DSN to")
        print("          your Supabase session-pooler string.")

    found = problems(dsn)
    if found:
        print()
        print("!! DB_DSN is not usable:")
        for item in found:
            print(f"   - {item}")
        return 1

    error = asyncio.run(try_connect())
    if error is None:
        print("    connection OK")
        return 0

    print()
    print(f"!! Could not connect to the database: {error}")
    lowered = error.lower()
    if "password authentication" in lowered:
        print("   A Supabase host answered and refused these credentials. Either:")
        print("     - the password is wrong, or")
        print("     - the username/host belong to a DIFFERENT project than yours.")
        print("   Check the username after 'postgres.' matches your project's")
        print("   reference and the host names your project's region, then compare")
        print("   against Project Settings -> Database -> Connection string.")
    elif "could not translate host name" in lowered or "nodename" in lowered:
        print("   The hostname does not resolve — the string was truncated or mistyped.")
    elif "timeout" in lowered or "timed out" in lowered:
        print("   The host did not answer. Check the Supabase project is not paused.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
