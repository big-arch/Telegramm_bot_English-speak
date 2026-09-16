"""Composition root.

Runs in one of two modes:

- **polling** (default) — the bot asks Telegram for updates. Right for a laptop
  or an always-on VM. Needs no public address and no TLS.
- **webhook** (set `WEBHOOK_BASE_URL`) — Telegram POSTs updates to us. Required
  on free hosting that sleeps an idle service, because Telegram's own request
  is what wakes it back up.

Never both: a live webhook makes `getUpdates` return nothing, and the bot looks
dead with no error anywhere. Each mode clears the other's state at startup.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent, Message
from aiohttp import web

from bot.config import settings
from bot.db.base import engine, sessionmaker
from bot.db.repositories import UserRepo
from bot.handlers import router as root_router
from bot.middlewares import DbSessionMiddleware, ThrottlingMiddleware, UserMiddleware
from bot.texts import ERROR_GENERIC

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="talk", description="Начать разговор"),
    BotCommand(command="finish", description="Закончить и получить разбор"),
    BotCommand(command="review", description="Повторить слова"),
    BotCommand(command="progress", description="Мой прогресс"),
    BotCommand(command="mistakes", description="Мои ошибки"),
    BotCommand(command="settings", description="Настройки"),
    BotCommand(command="help", description="Как это работает"),
]


def preflight() -> None:
    """Fail loudly at startup rather than inside a handler an hour later."""
    missing = settings.missing_keys()
    if missing:
        raise SystemExit(
            "Missing configuration:\n  - "
            + "\n  - ".join(missing)
            + "\n\nCopy .env.example to .env and fill those in."
        )

    logger.info(
        "providers: llm=%s stt=%s tts=%s db=%s mode=%s",
        settings.llm_provider,
        settings.stt_provider,
        settings.tts_provider,
        "sqlite" if settings.is_sqlite else "postgres",
        "webhook" if settings.use_webhook else "polling",
    )

    if settings.use_webhook and settings.is_sqlite:
        # Hosts that sleep an idle service also tend to wipe local disk. A
        # SQLite file there loses everyone's progress on the next redeploy.
        logger.warning(
            "webhook mode with SQLite: if this host has ephemeral disk, all "
            "progress is lost on redeploy. Point DB_DSN at Postgres/Supabase."
        )

    paid = []
    if settings.llm_provider == "anthropic":
        paid.append("LLM")
    if settings.stt_provider == "openai":
        paid.append("STT")
    if settings.tts_provider in {"openai", "elevenlabs"}:
        paid.append("TTS")
    logger.info(
        "billing: %s",
        "everything on free tiers — this run costs nothing"
        if not paid
        else f"paid providers in use for {', '.join(paid)}",
    )


def build_storage():
    """Redis where configured, memory otherwise.

    Conversation state lives in the database, not in FSM, so MemoryStorage only
    costs an interrupted onboarding on restart. That is an acceptable trade for
    not requiring Redis at all — but set REDIS_URL before running more than one
    process.
    """
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)

    logger.warning("REDIS_URL not set — using in-memory FSM storage (single process only)")
    return MemoryStorage()


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=build_storage())

    # Outer scope: runs once per update, before filters.
    dp.message.outer_middleware(ThrottlingMiddleware(period=0.7))
    dp.callback_query.outer_middleware(ThrottlingMiddleware(period=0.4))
    dp.update.outer_middleware(DbSessionMiddleware(sessionmaker))
    dp.update.outer_middleware(UserMiddleware())

    dp.include_router(root_router)

    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception("update failed", exc_info=event.exception)

        if isinstance(event.exception, TelegramForbiddenError):
            # The only reliable signal that a user blocked the bot. Record it,
            # or the active-user metric is fiction and rate budget keeps going
            # to chats that will never answer.
            tg_user = getattr(event.update.event, "from_user", None)
            if tg_user is not None:
                async with sessionmaker() as session:
                    await UserRepo(session).mark_blocked(tg_user.id)
            return True

        with suppress(Exception):
            message = event.update.message
            if isinstance(message, Message):
                await message.answer(ERROR_GENERIC)
        return True

    return dp


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def webhook_url() -> str:
    base = (settings.webhook_base_url or "").rstrip("/")
    if not base.startswith("https://"):
        raise SystemExit(
            f"WEBHOOK_BASE_URL must start with https:// — got {base!r}.\n"
            "Telegram refuses plain http for webhooks."
        )
    return f"{base}{settings.webhook_path}"


def build_app(bot: Bot, dp: Dispatcher, secret: str) -> web.Application:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    url = webhook_url()

    async def on_startup(_: web.Application) -> None:
        await bot.set_webhook(
            url=url,
            secret_token=secret,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
        await bot.set_my_commands(COMMANDS)
        logger.info("webhook set to %s", url)

    async def on_cleanup(_: web.Application) -> None:
        await bot.session.close()
        await engine.dispose()

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app = web.Application()
    # Two plain endpoints: the platform's health probe, and something to ping
    # if you want to keep a sleep-on-idle host awake.
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)

    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(
        app, path=settings.webhook_path
    )
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    # The webhook URL is guessable, so without a secret anyone can POST fake
    # updates. aiogram verifies the header and rejects mismatches.
    secret = (
        settings.webhook_secret.get_secret_value()
        if settings.webhook_secret
        else secrets.token_urlsafe(32)
    )
    app = build_app(bot, dp, secret)
    logger.info("listening on 0.0.0.0:%s", settings.port)
    web.run_app(app, host="0.0.0.0", port=settings.port, print=None)


async def _polling_main(bot: Bot, dp: Dispatcher) -> None:
    await bot.set_my_commands(COMMANDS)
    try:
        await run_polling(bot, dp)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    preflight()

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    if settings.use_webhook:
        # web.run_app owns the event loop, so this branch is not awaited.
        run_webhook(bot, dp)
    else:
        asyncio.run(_polling_main(bot, dp))


if __name__ == "__main__":
    main()
