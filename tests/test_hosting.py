"""Webhook mode and how the public URL is discovered.

The single most common way to end up with a silent bot on free hosting is
deploying it and leaving it in polling mode: nothing sends inbound traffic, so
the platform suspends the service and never wakes it. Picking the URL up from
the platform automatically is what removes that failure, so it is worth
covering properly.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

import bot.__main__ as entry
from bot.config import settings

FAKE_TOKEN = "123456789:AAFakeTokenForTestsOnly_xxxxxxxxxxxxx"


@pytest.fixture(autouse=True)
def _clean_hosting(monkeypatch):
    monkeypatch.setattr(settings, "webhook_base_url", None)
    monkeypatch.setattr(settings, "render_external_url", None)


def test_polling_when_nothing_is_configured(monkeypatch):
    """A laptop run should poll: no public address, no webhook."""
    assert settings.use_webhook is False


def test_render_url_alone_switches_to_webhook(monkeypatch):
    """Render injects this into every web service — no manual step needed."""
    monkeypatch.setattr(settings, "render_external_url", "https://speakout-abc.onrender.com")
    assert settings.use_webhook is True
    assert entry.webhook_url() == "https://speakout-abc.onrender.com/tg/webhook"


def test_explicit_setting_wins_over_the_platform(monkeypatch):
    """So a custom domain can override what the host provides."""
    monkeypatch.setattr(settings, "render_external_url", "https://speakout-abc.onrender.com")
    monkeypatch.setattr(settings, "webhook_base_url", "https://speak.example.com")
    assert entry.webhook_url() == "https://speak.example.com/tg/webhook"


def test_trailing_slash_does_not_produce_a_double_slash(monkeypatch):
    monkeypatch.setattr(settings, "webhook_base_url", "https://example.onrender.com/")
    assert entry.webhook_url() == "https://example.onrender.com/tg/webhook"


def test_plain_http_is_refused(monkeypatch):
    """Telegram rejects http:// webhooks — better to fail at boot than to
    deploy something that silently never receives an update."""
    monkeypatch.setattr(settings, "webhook_base_url", "http://example.onrender.com")
    with pytest.raises(SystemExit):
        entry.webhook_url()


@pytest.mark.asyncio
async def test_health_endpoint_answers(monkeypatch, aiohttp_client):
    """The platform probes this, and an uptime monitor pings it to stop a
    free instance from sleeping. A 404 here looks like an unhealthy deploy."""
    monkeypatch.setattr(settings, "webhook_base_url", "https://example.onrender.com")
    bot = Bot(token=FAKE_TOKEN, default=DefaultBotProperties())
    dp = Dispatcher()
    app = entry.build_app(bot, dp, secret="test-secret")
    app.on_startup.clear()
    app.on_cleanup.clear()

    client = await aiohttp_client(app)
    for path in ("/", "/healthz"):
        response = await client.get(path)
        assert response.status == 200
        assert (await response.json()) == {"ok": True}

    await bot.session.close()


@pytest.mark.asyncio
async def test_webhook_rejects_a_request_without_the_secret(monkeypatch, aiohttp_client):
    """The webhook path is guessable. Without secret-token checking, anyone
    could POST fabricated updates to the bot."""
    monkeypatch.setattr(settings, "webhook_base_url", "https://example.onrender.com")
    bot = Bot(token=FAKE_TOKEN, default=DefaultBotProperties())
    dp = Dispatcher()
    app = entry.build_app(bot, dp, secret="test-secret")
    app.on_startup.clear()
    app.on_cleanup.clear()

    client = await aiohttp_client(app)
    response = await client.post(settings.webhook_path, json={"update_id": 1})
    assert response.status != 200

    await bot.session.close()


def test_blank_db_dsn_falls_back_instead_of_crashing(monkeypatch):
    """A variable left empty in a hosting dashboard arrives as "".

    Without the fallback it reaches SQLAlchemy as an unparseable URL and the
    container dies on its first line with a trace that says nothing useful.
    """
    from bot.config import DEFAULT_DB_DSN, Settings

    for blank in ("", "   "):
        s = Settings(bot_token="x", groq_api_key="k", db_dsn=blank)
        assert s.db_dsn == DEFAULT_DB_DSN

    s = Settings(bot_token="x", groq_api_key="k", db_dsn="  postgresql+asyncpg://a/b  ")
    assert s.db_dsn == "postgresql+asyncpg://a/b"
