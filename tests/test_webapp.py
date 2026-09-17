"""The Mini App's front door.

A Mini App URL is guessable and its endpoints are open to the internet. The
only thing separating "the learner saved a word" from "anyone can write to any
account" is the initData signature, so these tests are about forgery before
they are about features.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.db.base import Base, engine, sessionmaker
from bot.db.models import Session, Turn, User
from bot.services import translate
from bot.webapp import attach
from bot.webapp.auth import InvalidInitData, parse, telegram_id

TOKEN = "123456:TEST-TOKEN-NOT-A-REAL-ONE"


def sign(fields: dict, *, token: str = TOKEN) -> str:
    """Produce initData the way Telegram does, so the test exercises the real
    algorithm rather than agreeing with the implementation."""
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def valid(tg_id: int = 8_000_000_000, *, age: int = 0) -> str:
    return sign({
        "auth_date": str(int(time.time()) - age),
        "query_id": "AAEtest",
        "user": json.dumps({"id": tg_id, "first_name": "Test"}),
    })


def test_a_genuine_blob_identifies_its_learner():
    assert telegram_id(valid(777), bot_token=TOKEN) == 777


def test_a_tampered_user_id_is_refused():
    """The attack the signature exists to stop: keep the hash, swap the id,
    and write into somebody else's vocabulary."""
    data = valid(777)
    forged = data.replace("%22id%22%3A+777", "%22id%22%3A+778").replace(
        "%22id%22%3A777", "%22id%22%3A778"
    )
    assert forged != data, "the id must actually have been swapped"
    with pytest.raises(InvalidInitData):
        telegram_id(forged, bot_token=TOKEN)


def test_a_blob_signed_with_another_token_is_refused():
    other = sign({"auth_date": str(int(time.time())),
                  "user": json.dumps({"id": 1})}, token="999:SOMEONE-ELSES-BOT")
    with pytest.raises(InvalidInitData):
        telegram_id(other, bot_token=TOKEN)


def test_an_unsigned_blob_is_refused():
    plain = urlencode({"auth_date": str(int(time.time())),
                       "user": json.dumps({"id": 1})})
    with pytest.raises(InvalidInitData):
        telegram_id(plain, bot_token=TOKEN)
    with pytest.raises(InvalidInitData):
        telegram_id("", bot_token=TOKEN)


def test_a_stale_blob_is_refused():
    """A replayed blob is signed correctly for ever; only its age gives it
    away."""
    with pytest.raises(InvalidInitData):
        parse(valid(age=48 * 3600), bot_token=TOKEN)
    # ...and a fresh one still passes with the same limit in force.
    assert parse(valid(age=60), bot_token=TOKEN)["user"]["id"] == 8_000_000_000


def test_the_hash_field_is_not_part_of_what_is_signed():
    """Including `hash` in the check string makes every request fail; excluding
    `auth_date` makes expiry unenforceable. Both are easy to get wrong."""
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 5})}
    parsed = parse(sign(fields), bot_token=TOKEN)
    assert "hash" not in parsed
    assert parsed["auth_date"] == fields["auth_date"]


def test_the_page_exists_and_asks_telegram_who_is_reading():
    """The reader must never take a user id from the page's own query string."""
    from bot.webapp.routes import PAGE

    html = PAGE.read_text(encoding="utf-8")
    assert "telegram-web-app.js" in html
    assert "X-Telegram-Init-Data" in html
    assert "tg?.initData" in html


# --------------------------------------------------------------------------- #
# The whole round trip: open a reply, tap a word, find it in the deck
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def reader(monkeypatch):
    """The Mini App served for real, over HTTP, against a real database."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker() as db:
        user = User(tg_id=4242, first_name="Test", productive_level="B1")
        db.add(user)
        await db.flush()
        convo = Session(user_id=user.id, persona_key="emma")
        db.add(convo)
        await db.flush()
        turn = Turn(
            session_id=convo.id, user_id=user.id, modality="text",
            user_text="hi", assistant_text="The queue was stubborn today.",
        )
        db.add(turn)
        await db.commit()
        turn_id, other_user_id = turn.id, user.id

        stranger = User(tg_id=777, first_name="Stranger")
        db.add(stranger)
        await db.commit()

    async def fake_look_up(word, *, context=""):
        return translate.WordSense(
            lemma=word.lower(), translation_ru="упрямый", pos="adjective",
            note_ru="",
        )

    monkeypatch.setattr(translate, "look_up", fake_look_up)

    app = web.Application()
    attach(app, bot_token=TOKEN)
    async with TestClient(TestServer(app)) as client:
        yield client, turn_id, other_user_id

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_tapping_a_word_end_to_end(reader):
    client, turn_id, _ = reader
    headers = {"X-Telegram-Init-Data": valid(4242)}

    opened = await (await client.get(f"/api/turn?turn={turn_id}", headers=headers)).json()
    assert opened["text"] == "The queue was stubborn today."
    assert opened["saved"] == []

    tapped = await (
        await client.post(
            "/api/word",
            json={"word": "stubborn", "context": "The queue was stubborn today."},
            headers=headers,
        )
    ).json()
    assert tapped == {
        "lemma": "stubborn", "translation": "упрямый",
        "pos": "adjective", "note": "", "added": True,
    }

    # Reopening must show it already red, or the reader looks like it forgot.
    reopened = await (await client.get(f"/api/turn?turn={turn_id}", headers=headers)).json()
    assert reopened["saved"] == ["stubborn"]

    # And it can be taken back.
    removed = await (
        await client.post("/api/word/remove", json={"lemma": "stubborn"}, headers=headers)
    ).json()
    assert removed == {"removed": True}
    again = await (await client.get(f"/api/turn?turn={turn_id}", headers=headers)).json()
    assert again["saved"] == []


@pytest.mark.asyncio
async def test_one_learner_cannot_read_another_learners_conversation(reader):
    """A reader that could be pointed at any turn id would leak whole
    conversations to anyone who can count."""
    client, turn_id, _ = reader
    response = await client.get(
        f"/api/turn?turn={turn_id}", headers={"X-Telegram-Init-Data": valid(777)}
    )
    assert response.status == 403


@pytest.mark.asyncio
async def test_an_unsigned_tap_writes_to_nobodys_vocabulary(reader):
    client, turn_id, _ = reader
    response = await client.post("/api/word", json={"word": "stubborn"})
    assert response.status == 401

    forged = valid(4242) + "&user=%7B%22id%22%3A+1%7D"
    response = await client.post(
        "/api/word", json={"word": "stubborn"},
        headers={"X-Telegram-Init-Data": forged},
    )
    assert response.status == 401
