"""Webhook mode.

Free hosting sleeps an idle service, and Telegram's own POST is what wakes it
back up — so webhook mode is not a nicety there, it is the only mode that
works. These tests cover the parts that would silently break a deployment.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

import bot.__main__ as entry
from bot.config import settings

FAKE_TOKEN = "123456789:AAFakeTokenForTestsOnly_xxxxxxxxxxxxx"


@pytest.fixture
def webhook_settings(monkeypatch):
    monkeypatch.setattr(settings, "webhook_base_url", "https://example.koyeb.app")
    return settings


def test_polling_is_the_default(monkeypatch):
    monkeypatch.setattr(settings, "webhook_base_url", None)
    assert settings.use_webhook is False


def test_setting_a_base_url_switches_to_webhook(webhook_settings):
    assert settings.use_webhook is True
    assert entry.webhook_url() == "https://example.koyeb.app/tg/webhook"


def test_trailing_slash_does_not_produce_a_double_slash(monkeypatch):
    monkeypatch.setattr(settings, "webhook_base_url", "https://example.koyeb.app/")
    assert entry.webhook_url() == "https://example.koyeb.app/tg/webhook"


def test_plain_http_is_refused(monkeypatch):
    """Telegram rejects http:// webhooks — better to fail at boot than to
    deploy something that silently never receives an update."""
    monkeypatch.setattr(settings, "webhook_base_url", "http://example.koyeb.app")
    with pytest.raises(SystemExit):
        entry.webhook_url()


@pytest.mark.asyncio
async def test_health_endpoint_answers(webhook_settings, aiohttp_client):
    """Hosting platforms probe this, and it is what you ping to keep a
    sleep-on-idle service awake. If it 404s the deployment looks unhealthy."""
    bot = Bot(token=FAKE_TOKEN, default=DefaultBotProperties())
    dp = Dispatcher()
    app = entry.build_app(bot, dp, secret="test-secret")

    # Skip the Telegram calls in on_startup; we are testing the HTTP surface.
    app.on_startup.clear()
    app.on_cleanup.clear()

    client = await aiohttp_client(app)
    for path in ("/", "/healthz"):
        response = await client.get(path)
        assert response.status == 200
        assert (await response.json()) == {"ok": True}

    await bot.session.close()


@pytest.mark.asyncio
async def test_webhook_rejects_a_request_without_the_secret(webhook_settings, aiohttp_client):
    """The webhook path is guessable. Without secret-token checking, anyone
    could POST fabricated updates to the bot."""
    bot = Bot(token=FAKE_TOKEN, default=DefaultBotProperties())
    dp = Dispatcher()
    app = entry.build_app(bot, dp, secret="test-secret")
    app.on_startup.clear()
    app.on_cleanup.clear()

    client = await aiohttp_client(app)
    response = await client.post(settings.webhook_path, json={"update_id": 1})
    assert response.status != 200

    await bot.session.close()
