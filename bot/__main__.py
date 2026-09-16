"""Composition root."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent, Message

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


def build_storage():
    """Redis where configured, memory otherwise.

    Conversation state lives in Postgres, not in FSM, so MemoryStorage only
    costs an interrupted onboarding on restart. That is an acceptable trade for
    not requiring Redis to run the bot at all — but set REDIS_URL before running
    more than one replica.
    """
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)

    logger.warning("REDIS_URL not set — using in-memory FSM storage (single process only)")
    return MemoryStorage()


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
        "providers: llm=%s stt=%s tts=%s db=%s",
        settings.llm_provider,
        settings.stt_provider,
        settings.tts_provider,
        "sqlite" if settings.is_sqlite else "postgres",
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


async def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    preflight()

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
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
            # or your active-user metric is fiction and you keep spending rate
            # budget on chats that will never answer.
            user = event.update.event.from_user if hasattr(event.update.event, "from_user") else None
            if user is not None:
                async with sessionmaker() as session:
                    await UserRepo(session).mark_blocked(user.id)
            return True

        with suppress(Exception):
            message = event.update.message
            if isinstance(message, Message):
                await message.answer(ERROR_GENERIC)
        return True

    await bot.set_my_commands(COMMANDS)

    # A live webhook makes getUpdates silently return nothing, and the bot looks
    # dead with no error anywhere.
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
