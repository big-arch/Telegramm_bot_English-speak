---
name: telegram-bot-aiogram
description: Building, debugging and shipping Telegram bots with Python and aiogram 3.x — handlers, routers, FSM dialogs, middlewares, inline/reply keyboards, callback data, voice and media, Telegram Stars payments, rate limits and flood control, polling vs webhook deployment. Use this skill whenever the work touches a Telegram bot in any way: writing a new handler, designing a conversation flow, fixing "button does nothing" / "state is lost" / "Flood control exceeded" bugs, choosing between polling and webhooks, handling voice messages, or reviewing bot code — even if the user never says the word "aiogram".
---

# Telegram bots with aiogram 3.x

Telegram bots fail in a small number of predictable ways: state that leaks between users, callbacks that never get answered, blocking calls that freeze the event loop, and flood limits hit in production but never in testing. This skill encodes the architecture that avoids those, plus the platform facts that are easy to get wrong.

Assume **aiogram 3.x** (the 2.x API — `executor`, `types.Message.reply`, decorators on `Dispatcher` — is gone and its idioms will not work). If the project pins 2.x, say so explicitly and migrate rather than mixing idioms.

## Project layout that scales

A single `main.py` stops working around the third feature. Start here instead:

```
bot/
├── __main__.py          # composition root: config → bot → dp → run
├── config.py            # pydantic-settings, all env in one typed object
├── handlers/            # one Router per feature area
│   ├── __init__.py      # collects routers in order
│   ├── start.py
│   ├── lesson.py
│   └── settings.py
├── keyboards/           # builders, never inline literals in handlers
├── middlewares/         # db session, throttling, i18n, user loading
├── states.py            # StatesGroup definitions
├── callbacks.py         # CallbackData factories
├── services/            # business logic — no aiogram imports here
└── db/                  # models, repositories, migrations
```

The rule that earns its keep: **`services/` must not import aiogram.** Business logic that knows about `Message` objects cannot be unit-tested, reused for a web API, or driven from a cron job. Handlers extract data from the update, call a service, and format the reply.

## Composition root

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from bot.config import settings
from bot.handlers import router as root_router
from bot.middlewares.db import DbSessionMiddleware


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=RedisStorage.from_url(settings.redis_dsn))

    dp.update.middleware(DbSessionMiddleware(sessionmaker))
    dp.include_router(root_router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
```

Details that matter:

- `MemoryStorage` loses every dialog on restart and cannot be scaled to more than one process. It is fine for local runs only — use `RedisStorage` anywhere real.
- `resolve_used_update_types()` tells Telegram to stop sending update types nobody handles. Free bandwidth and fewer wasted wakeups.
- `parse_mode` belongs in `DefaultBotProperties`, not repeated in every `answer()` call.
- Never put the token in code. `pydantic-settings` with `SecretStr` keeps it out of logs and tracebacks.

## Routers, not decorators on the dispatcher

```python
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="lesson")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None: ...


@router.message(Command("lesson"))
async def cmd_lesson(message: Message) -> None: ...


@router.message(F.voice)
async def on_voice(message: Message) -> None: ...
```

Order is significant: the **first matching handler wins**, and routers are checked in the order they were included. Put narrow filters before broad ones, and register catch-all handlers (`@router.message()` with no filter) in the last router. A catch-all registered early silently swallows every later feature — this is the single most common "my handler never fires" cause.

`F` is the magic-filter DSL: `F.text`, `F.data.startswith("x")`, `F.photo`, `F.chat.type == "private"`, `F.from_user.id.in_(admins)`. Prefer it over writing lambda filters.

## FSM: dialogs that survive restarts

```python
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    choosing_level = State()
    choosing_goal = State()
    confirming = State()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.set_state(Onboarding.choosing_level)
    await message.answer("What's your level?", reply_markup=level_kb())


@router.callback_query(LevelCB.filter(), Onboarding.choosing_level)
async def pick_level(query: CallbackQuery, callback_data: LevelCB, state: FSMContext) -> None:
    await state.update_data(level=callback_data.level)
    await state.set_state(Onboarding.choosing_goal)
    await query.message.edit_text("What's your goal?", reply_markup=goal_kb())
    await query.answer()
```

Rules worth internalising:

- FSM state is keyed by `(bot_id, chat_id, user_id)`. In groups, two users have independent states in the same chat — do not assume one dialog per chat.
- `state.get_data()` returns a plain dict. It is not a database. Keep it small (ids and choices), and persist anything that must outlive the dialog. A dict that grows to hold lesson content will silently blow up Redis memory and make every step slower.
- Always `await state.clear()` at the end of a flow and on `/cancel`. Orphaned state means the user's next unrelated message gets eaten by a stale handler.
- Filter handlers by state (`Onboarding.choosing_goal` above) rather than checking state inside the handler — that is what keeps flows from colliding.

## Callbacks: typed, prefixed, always answered

```python
from aiogram.filters.callback_data import CallbackData


class AnswerCB(CallbackData, prefix="ans"):
    card_id: int
    grade: int


kb = InlineKeyboardBuilder()
kb.button(text="Again", callback_data=AnswerCB(card_id=card.id, grade=1))
kb.button(text="Good", callback_data=AnswerCB(card_id=card.id, grade=3))
kb.adjust(2)


@router.callback_query(AnswerCB.filter())
async def on_answer(query: CallbackQuery, callback_data: AnswerCB) -> None:
    await grade_card(callback_data.card_id, callback_data.grade)
    await query.answer()  # stops the client-side spinner
```

Two hard platform constraints:

- **`callback_data` is capped at 64 bytes.** Pack ids, never text. If you need more, store a payload row and pass its id.
- **Every `CallbackQuery` must be answered** within ~15 seconds or the user sees a hanging spinner and eventually an error. `await query.answer()` even when there is nothing to show. Put it in a `finally` if the handler can raise.

`edit_text` raises `TelegramBadRequest: message is not modified` when the new text and markup are byte-identical to the old. Either vary the content, or catch that specific error and ignore it.

## Middlewares

Middlewares are where cross-cutting concerns live: a DB session per update, the current user row, throttling, i18n.

```python
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def __call__(self, handler, event: TelegramObject, data: dict):
        async with self.sessionmaker() as session:
            data["session"] = session
            return await handler(event, data)
```

Anything put into `data` becomes an injectable handler argument (`async def h(message: Message, session: AsyncSession)`). Register on `dp.update.middleware(...)` for outer scope (runs once per update, before filters) or `router.message.middleware(...)` for a specific observer.

Throttling belongs here too — see `references/rate-limits.md` for a working `TelegramRetryAfter`-aware throttle.

## The async rules that actually bite

- **Never call blocking code in a handler.** `requests`, `time.sleep`, `openai.OpenAI().chat...` (sync client), `subprocess.run`, `psycopg2`, PIL on a big image — each one freezes *every* user's bot for its duration, because it is one event loop. Use async clients, or `await asyncio.to_thread(fn, ...)`.
- **Long work must not block the update.** Transcribing a voice message takes seconds. Answer immediately ("🎧 listening…"), then do the work, then `edit_text` the result. Users who wait with no feedback press the button again, which doubles your load.
- One `aiohttp` session is reused by the `Bot` object. Do not create a `Bot` per request; create it once and pass it (it is available as `bot` in handler injection).

## Rate limits — design for them, not around them

Telegram's practical limits: **~30 messages/second overall**, **~1 message/second to the same chat**, **~20 messages/minute to the same group**. A broadcast to 5 000 users sent in a loop will hit `TelegramRetryAfter` within seconds and can get the bot temporarily restricted.

Exceeding limits raises `aiogram.exceptions.TelegramRetryAfter` with `.retry_after`. Respect it — retrying immediately extends the ban.

Read `references/rate-limits.md` before writing any broadcast, mailing, or notification loop.

## Voice, audio and files

An English-speaking bot lives on voice messages. The essentials:

- `message.voice` gives `file_id`, `duration`, `mime_type` (`audio/ogg`, OPUS codec).
- `bot.get_file(file_id)` → `bot.download_file(file.file_path)`. **The Bot API caps downloads at 20 MB** (and uploads at 50 MB). Longer recordings need a local Bot API server.
- `file_id` is reusable for sending the same file back with zero upload cost, but it is **bot-specific and not permanent** — store `file_unique_id` for deduplication, and re-upload if a send fails.
- OGG/OPUS goes straight into Whisper-family models; for anything else convert with `ffmpeg` in a thread, not in the loop.

See `references/voice-and-media.md` for the download → transcribe → reply pipeline including temp-file hygiene.

## Payments

Telegram Stars (`XTR`) is the only way to sell digital goods in-bot, and it needs no provider token:

```python
await bot.send_invoice(
    chat_id=chat_id,
    title="Premium month",
    description="Unlimited speaking practice",
    payload="premium_1m",
    currency="XTR",
    prices=[LabeledPrice(label="Premium", amount=250)],  # 250 Stars
)
```

You must answer `pre_checkout_query` within 10 seconds (`await query.answer(ok=True)`) or the payment fails, then grant access on the `successful_payment` update. Star payments are refundable via `refundStarPayment` for 21 days — build the grant so it can be revoked.

## Webhooks vs polling

Polling is right for development and for bots under a few thousand users: no TLS, no public IP, trivially restartable. Webhooks are right when latency matters or you run multiple replicas. Do not run both at once — `start_polling` with an active webhook silently receives nothing, which is why the composition root above calls `delete_webhook` first.

Deployment, webhook setup, graceful shutdown and health checks: `references/deployment.md`.

## Debugging checklist

When a bot "doesn't work", walk this list in order — it resolves the large majority of cases:

1. **Handler never fires** → an earlier router/handler matched first; or the filter is wrong; or the update type is not in `allowed_updates`; or the bot is in a group without privacy mode disabled (by default group bots only see commands and replies).
2. **State lost between steps** → `MemoryStorage` with a restart, or missing `state.set_state`, or the handler is not filtered by state so a different one caught the message.
3. **Button spins forever** → missing `query.answer()`.
4. **`message is not modified`** → editing with identical content.
5. **`Flood control exceeded`** → see rate limits.
6. **Everything is slow for everyone** → a blocking call in a handler.
7. **Two replies to one message** → two processes polling the same token, or a duplicated `include_router`.

## Reference files

- `references/rate-limits.md` — throttling middleware, safe broadcast with backoff, `TelegramRetryAfter` handling.
- `references/voice-and-media.md` — voice download/transcribe pipeline, `file_id` semantics, ffmpeg conversion, size limits.
- `references/deployment.md` — webhook server, Docker, graceful shutdown, health checks, multi-replica notes.
