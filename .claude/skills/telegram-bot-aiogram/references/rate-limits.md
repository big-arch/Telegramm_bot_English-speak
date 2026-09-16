# Rate limits, throttling and broadcasts

## The actual limits

Telegram does not publish exact numbers, but these are the operational ones the Bot API enforces:

| Scope | Limit |
|---|---|
| Total outgoing messages | ~30 / second |
| Same private chat | ~1 / second (short bursts tolerated) |
| Same group/supergroup | ~20 / minute |
| `getUpdates` long polling | no practical limit |
| Bulk notifications | ~30 / second is the ceiling; aim for 20–25 |

Exceeding them raises `aiogram.exceptions.TelegramRetryAfter` carrying `.retry_after` (seconds). Retrying before that window expires extends the restriction, so the only correct response is to sleep for exactly that long and try once more.

## Incoming throttling middleware

Protects your own backend (and your LLM bill) from a user holding down a button. Keyed per user, with a short TTL cache.

```python
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from cachetools import TTLCache


class ThrottlingMiddleware(BaseMiddleware):
    """Drop updates from a user who exceeds `rate` events per `period` seconds."""

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
            # Silent for messages; callbacks still need an answer or the
            # client spins forever.
            if isinstance(event, CallbackQuery):
                await event.answer("Slow down a little 🙂", show_alert=False)
            return None

        self.cache[user.id] = count + 1
        return await handler(event, data)
```

Register as an outer middleware so it runs before filters and before the DB session is opened:

```python
dp.message.outer_middleware(ThrottlingMiddleware())
dp.callback_query.outer_middleware(ThrottlingMiddleware(period=0.4))
```

Use a Redis counter instead of `TTLCache` if the bot runs in more than one process — an in-process cache throttles per replica, which multiplies the effective limit by the replica count.

## Safe send with backoff

Wrap every outgoing call that can legitimately fail. The three errors below cover nearly all real failures:

```python
import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

logger = logging.getLogger(__name__)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    """Send once, honouring one RetryAfter. Returns False if the user is gone."""
    for attempt in range(2):
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return True
        except TelegramRetryAfter as e:
            logger.warning("flood: sleeping %ss", e.retry_after)
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            # User blocked the bot or deleted their account — mark inactive.
            await deactivate_user(chat_id)
            return False
        except TelegramBadRequest as e:
            logger.error("bad request for %s: %s", chat_id, e)
            return False
    return False
```

`TelegramForbiddenError` is the important one for retention metrics: it is the only reliable signal that a user blocked the bot. Record it, and stop sending — continuing to hammer blocked chats burns your rate budget on nothing.

## Broadcasting to many users

Never `asyncio.gather` a mailing list. Pace it explicitly:

```python
async def broadcast(bot: Bot, user_ids: list[int], text: str, rate: int = 20) -> dict[str, int]:
    """Send to everyone at `rate` messages per second. Returns a delivery summary."""
    delay = 1 / rate
    stats = {"sent": 0, "blocked": 0, "failed": 0}

    for chat_id in user_ids:
        ok = await safe_send(bot, chat_id, text)
        if ok:
            stats["sent"] += 1
        else:
            stats["blocked"] += 1
        await asyncio.sleep(delay)

    return stats
```

At 20/s, 100 000 users takes ~85 minutes. That is expected and fine — a broadcast is a background job, not a request handler. Run it from a task queue (or at minimum `asyncio.create_task` with progress persisted), make it resumable by storing the last delivered offset, and report progress to the admin who started it.

For scheduled lesson reminders, spread sends across the target window rather than firing all of them at the top of the hour: bucket users by minute and process one bucket per minute. A learning bot with 50 000 users and a single 09:00 reminder is a self-inflicted flood.

## Rule of thumb

Any code path that can send more than one message per user action, or one message to more than one user, needs an explicit pacing decision written down next to it. If there is no `sleep`, no semaphore and no queue in a loop that calls the Bot API, that is a bug waiting for scale.
