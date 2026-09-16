from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.db.repositories import UserRepo


class UserMiddleware(BaseMiddleware):
    """Load (or create) the User row and inject it as `user`.

    Doing this once per update rather than in every handler keeps handlers to
    one job, and means a user row always exists by the time any handler runs —
    including for someone whose first ever message is a voice note rather than
    /start.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        session = data.get("session")
        if tg_user is None or session is None:
            return await handler(event, data)

        user, is_new = await UserRepo(session).get_or_create(
            tg_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            language_code=tg_user.language_code,
        )
        data["user"] = user
        data["is_new_user"] = is_new
        return await handler(event, data)
