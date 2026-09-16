# Deployment: polling, webhooks, containers, shutdown

## Choosing polling or webhooks

| | Polling | Webhook |
|---|---|---|
| Public IP / TLS | not needed | required (443, 80, 88, 8443) |
| Latency | ~1 update per long-poll cycle | immediate |
| Multiple replicas | impossible on one token | natural |
| Local development | trivial | needs a tunnel |
| Failure mode | reconnects itself | silent if the endpoint 500s |

Polling until the bot is genuinely busy. Switch to webhooks when you need horizontal scaling or sub-second delivery — not because it sounds more professional.

Never run both: a live webhook makes `getUpdates` return nothing, and the bot appears dead with no error. `bot.delete_webhook(drop_pending_updates=True)` before `start_polling` removes a whole class of "works on my machine" confusion.

## Webhook server

```python
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = settings.webhook_secret.get_secret_value()


async def on_startup(bot: Bot) -> None:
    await bot.set_webhook(
        url=f"{settings.base_url}{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )


def main() -> None:
    dp.startup.register(on_startup)

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.router.add_get("/healthz", lambda _: web.json_response({"ok": True}))
    web.run_app(app, host="0.0.0.0", port=8080)
```

`secret_token` is not optional in practice: the webhook URL is guessable and without it anyone can POST fake updates to your bot. aiogram verifies the `X-Telegram-Bot-Api-Secret-Token` header and rejects mismatches.

Telegram retries a webhook that returns a non-2xx status, so a handler that raises produces duplicate processing. Return 200 fast and do slow work in a task.

## Graceful shutdown

A container killed mid-handler loses an in-flight lesson and can leave a DB transaction open. Register teardown on the dispatcher:

```python
async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()
    await engine.dispose()
    await redis.aclose()

dp.shutdown.register(on_shutdown)
```

`dp.start_polling` already handles SIGINT/SIGTERM and stops accepting new updates while letting running handlers finish. Give the container a `stop_grace_period` of at least 30 s so that actually happens.

## Dockerfile

```dockerfile
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 1000 bot && chown -R bot:bot /app
USER bot

CMD ["python", "-m", "bot"]
```

`ffmpeg` is needed for any voice pipeline and is absent from slim images. Running as non-root is cheap and expected. Do not bake the token into the image — pass it as an environment variable or a secret mount.

## Configuration

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: SecretStr
    db_dsn: str
    redis_dsn: str = "redis://localhost:6379/0"
    base_url: str | None = None
    webhook_secret: SecretStr | None = None
    admin_ids: list[int] = []


settings = Settings()
```

Typed settings fail loudly at startup when something is missing, which is far better than a `KeyError` inside a handler an hour later. `SecretStr` keeps the token out of `repr()` and therefore out of Sentry.

`.env` belongs in `.gitignore`; commit a `.env.example` with empty values so the required set is documented.

## Error handling and observability

```python
from aiogram.types import ErrorEvent


@dp.error()
async def on_error(event: ErrorEvent) -> bool:
    logger.exception("update failed: %s", event.update.event_id, exc_info=event.exception)
    # Tell the user something went wrong rather than leaving them hanging.
    with suppress(Exception):
        if event.update.message:
            await event.update.message.answer("Something broke on my side. Try again in a moment.")
    return True  # handled; don't re-raise
```

Log the `user_id` on every handler entry — without it, production logs are unreadable. Structured logging (`extra={"user_id": ...}`) beats string interpolation when you need to trace one user's session.

Track at minimum: updates/second, handler latency p95, Bot API error counts by type (especially `TelegramRetryAfter` and `TelegramForbiddenError`), and queue depth if you have one.

## Running more than one replica

- Webhooks only — polling with two processes on one token double-delivers every update.
- `RedisStorage` for FSM, never `MemoryStorage`.
- Any in-process cache (throttling, dedup) becomes per-replica; move counters to Redis.
- Scheduled jobs need a single owner — use a lock in Redis or a dedicated scheduler container, or every replica will send the same reminder.

## Pre-deploy checklist

- `delete_webhook` / `set_webhook` matches the chosen mode.
- Token, DB DSN and secrets come from the environment.
- Migrations run before the new image serves traffic.
- `ffmpeg` present if voice is used.
- Health endpoint wired to the orchestrator.
- Graceful shutdown closes bot session, DB engine and Redis.
- Error handler registered and reporting somewhere you read.
