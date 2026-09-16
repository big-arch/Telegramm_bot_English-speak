"""Check the configuration at startup and say plainly what is wrong.

"Failed deploy" plus a traceback tells a person nothing they can act on, and a
model name that quietly went out of service tells them even less — it surfaces
as "something broke on my side" on the first voice message a learner sends.

This runs before anything else and covers both: it verifies the Groq model
names still exist (listing what does, when they do not), then checks the
database connection string for the mistakes that actually happen, echoing it
back with the password masked so a placeholder left unreplaced is visible at a
glance.

    python -m scripts.doctor

Exits non-zero when the bot would not work.
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


GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"


def check_groq_models() -> list[str]:
    """Verify the configured Groq model names still exist.

    Providers retire models on a few months' notice, and a decommissioned name
    fails at the first real request — which here means the first voice message
    a learner sends, reported to them as "something broke on my side". Checking
    at startup turns that into a deploy-time message naming the replacement.
    """
    import httpx

    if settings.groq_api_key is None:
        return ["GROQ_API_KEY is not set."]

    wanted: dict[str, str] = {}
    if settings.llm_provider == "groq":
        wanted[settings.groq_chat_model] = "GROQ_CHAT_MODEL"
        wanted[settings.groq_assessor_model] = "GROQ_ASSESSOR_MODEL"
    if settings.stt_provider == "groq":
        from bot.services.stt import MODELS

        wanted[MODELS["groq"]] = "speech recognition"

    if not wanted:
        return []

    try:
        response = httpx.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}"},
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        return [f"Could not reach Groq to verify models: {exc}"]

    if response.status_code == 401:
        return ["GROQ_API_KEY was rejected. Create a new key at console.groq.com/keys."]
    if response.status_code != 200:
        return [f"Groq answered {response.status_code} when listing models."]

    available = sorted(m["id"] for m in response.json().get("data", []))
    missing = [(name, where) for name, where in wanted.items() if name not in available]
    if not missing:
        return []

    report = [
        f"{where}: '{name}' no longer exists on Groq." for name, where in missing
    ]
    chat = [m for m in available if "whisper" not in m]
    report.append("Available models right now: " + ", ".join(chat[:20]))
    report.append(
        "Set GROQ_CHAT_MODEL and GROQ_ASSESSOR_MODEL to one of those and redeploy."
    )
    return report


def main() -> int:
    problems_found = False

    if settings.llm_provider == "groq" or settings.stt_provider == "groq":
        issues = check_groq_models()
        if issues:
            problems_found = True
            print("!! Groq models:")
            for item in issues:
                print(f"   - {item}")
            print()
        else:
            print("    groq models OK")

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
    if error is not None:
        print()
        print(f"!! Could not connect to the database: {error}")
        explain_connection_error(error)
        return 1

    print("    connection OK")
    return 1 if problems_found else 0


def explain_connection_error(error: str) -> None:
    """Turn a driver error into the action that fixes it."""
    lowered = error.lower()
    if "tenant" in lowered and "not found" in lowered:
        # Supabase's pooler answering this means the project reference is being
        # looked up on a pooler that does not serve it: the ref is usually
        # right and the HOST is wrong. Guessing the host from a region name
        # does not work — the prefix (aws-0 / aws-1 / ...) is assigned per
        # project and only the dashboard knows it.
        print("   The pooler answered but does not serve this project, which means")
        print("   the HOST is wrong — not the project reference and not the password.")
        print("   Do not construct the host by hand. In Supabase press the green")
        print("   'Connect' button at the top, choose 'Session pooler', and copy the")
        print("   URI exactly as shown; then change only 'postgresql://' to")
        print("   'postgresql+asyncpg://' and fill in the password.")
    elif "password authentication" in lowered:
        # Reaching this means the pooler resolved the tenant — otherwise it
        # would have said "tenant not found" instead. So the host and the
        # project reference are right, and only the password is wrong. Do not
        # send anyone back to re-check the address.
        print("   The pooler found your project, so the host and the project")
        print("   reference are correct. Only the password is wrong.")
        print()
        print("   Do not try to remember it — reset it:")
        print("     Supabase -> Project Settings -> Database -> Database password")
        print("     -> Reset database password")
        print("   Use letters and digits only (other characters break the URL),")
        print("   then put the new password into DB_DSN here and redeploy.")
    elif "could not translate host name" in lowered or "nodename" in lowered:
        print("   The hostname does not resolve - the string was truncated or mistyped.")
    elif "timeout" in lowered or "timed out" in lowered:
        print("   The host did not answer. Check the Supabase project is not paused.")


if __name__ == "__main__":
    sys.exit(main())
