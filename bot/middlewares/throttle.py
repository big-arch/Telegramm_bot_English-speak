from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject
from cachetools import TTLCache

from bot.texts import TOO_FAST


class ThrottlingMiddleware(BaseMiddleware):
    """Drop updates from a user firing faster than `period`.

    This protects the API bill as much as the bot: every voice turn is a
    transcription, two model calls and a synthesis. A user holding down a button
    is real money.

    Note this is per-process. With more than one replica the effective limit
    multiplies by the replica count — move the counter to Redis before scaling
    out.
    """

    def __init__(self, period: float = 0.7, max_events: int = 1) -> None:
        self.cache: TTLCache = TTLCache(maxsize=10_000, ttl=period)
        self.max_events = max_events

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        count = self.cache.get(user.id, 0)
        if count >= self.max_events:
            # Callbacks still need answering or the client spins forever.
            if isinstance(event, CallbackQuery):
                await event.answer(TOO_FAST, show_alert=False)
            return None

        self.cache[user.id] = count + 1
        return await handler(event, data)
