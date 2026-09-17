"""The reader's server side: hand it a turn, take back the words they tapped.

Three endpoints, and the shape of them is dictated by one rule — **nothing the
page sends about who it is may be believed.** The page says "I am learner 42"
by handing over Telegram's signed `initData`, and every endpoint re-verifies
that signature before touching a row. A tap writes to somebody's vocabulary; an
unverified tap writes to anybody's.

The text itself is never sent by the page either. The page names a turn by id
and the server fetches it, checking it belongs to that learner. Otherwise the
reader would be a way to put arbitrary text into someone else's lesson history.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from sqlalchemy import select

from bot.db.base import sessionmaker
from bot.db.models import Turn, User
from bot.db.repositories import CardRepo
from bot.services import translate
from bot.webapp.auth import InvalidInitData, telegram_id

logger = logging.getLogger(__name__)

PAGE = Path(__file__).parent / "reader.html"

# The learner's own words are their business; a reader that could be pointed at
# any turn id would leak whole conversations.
FORBIDDEN = "this turn does not belong to you"


def _init_data(request: web.Request, body: dict | None = None) -> str:
    """Telegram's signed blob, from the header or the body."""
    if body and isinstance(body.get("initData"), str):
        return body["initData"]
    return request.headers.get("X-Telegram-Init-Data", "")


async def _learner(request: web.Request, db, body: dict | None = None) -> User:
    token = request.app["bot_token"]
    try:
        tg_id = telegram_id(_init_data(request, body), bot_token=token)
    except InvalidInitData as exc:
        # Deliberately terse: a precise error here is a hint to whoever is
        # trying to forge one.
        logger.info("rejected webapp request: %s", exc)
        raise web.HTTPUnauthorized(text="not signed by Telegram")

    user = await db.scalar(select(User).where(User.tg_id == tg_id))
    if user is None:
        raise web.HTTPUnauthorized(text="unknown learner")
    return user


async def page(request: web.Request) -> web.Response:
    """The reader itself. Static — everything it needs it asks for."""
    return web.Response(
        body=PAGE.read_bytes(),
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-cache"},
    )


async def read_turn(request: web.Request) -> web.Response:
    """The text to read, plus which of its words are already being learned.

    Both in one call: the page must be able to paint a word red the moment it
    appears, not a flicker later, or reopening the reader looks like it forgot
    everything.
    """
    try:
        turn_id = int(request.query.get("turn", ""))
    except ValueError:
        raise web.HTTPBadRequest(text="turn must be a number")

    async with sessionmaker() as db:
        user = await _learner(request, db)
        turn = await db.get(Turn, turn_id)
        if turn is None or turn.user_id != user.id:
            raise web.HTTPForbidden(text=FORBIDDEN)

        known = await CardRepo(db).lemmas_for(user.id)

    return web.json_response(
        {"text": turn.assistant_text or "", "saved": sorted(known)}
    )


async def tap_word(request: web.Request) -> web.Response:
    """One word, tapped. Translate it in its sentence and put it in the deck."""
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="expected json")

    word = str(body.get("word", "")).strip()
    context = str(body.get("context", ""))[:400]
    if not translate.is_a_word(word):
        raise web.HTTPBadRequest(text="not a word")

    async with sessionmaker() as db:
        user = await _learner(request, db, body)
        repo = CardRepo(db)

        cached = await repo.translated(word.lower())
        if cached is not None:
            sense = translate.WordSense(
                lemma=cached.lemma,
                translation_ru=cached.translation_ru or "",
                pos=cached.pos,
            )
        else:
            found = await translate.look_up(word, context=context)
            if found is None:
                raise web.HTTPServiceUnavailable(text="could not translate")
            sense = found
            # The lemma may already be catalogued under a translation even when
            # the surface form was not: "ran" resolves to "run".
            if (known := await repo.translated(sense.lemma)) is not None:
                sense.translation_ru = known.translation_ru or sense.translation_ru

        _word, is_new = await repo.save_tapped(
            user_id=user.id,
            lemma=sense.lemma,
            translation_ru=sense.translation_ru,
            pos=sense.pos,
            cefr=user.receptive_level or "B1",
        )
        await db.commit()

    return web.json_response(
        {
            "lemma": sense.lemma,
            "translation": sense.translation_ru,
            "pos": sense.pos,
            "note": sense.note_ru,
            "added": is_new,
        }
    )


async def untap_word(request: web.Request) -> web.Response:
    """Undo. Mistaking a word is cheap; being stuck with it is what stops
    people tapping in the first place."""
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="expected json")

    lemma = str(body.get("lemma", "")).strip()
    if not translate.is_a_word(lemma):
        raise web.HTTPBadRequest(text="not a word")

    async with sessionmaker() as db:
        user = await _learner(request, db, body)
        removed = await CardRepo(db).forget(user_id=user.id, lemma=lemma)
        await db.commit()

    return web.json_response({"removed": removed})


def attach(app: web.Application, *, bot_token: str) -> None:
    app["bot_token"] = bot_token
    app.router.add_get("/app", page)
    app.router.add_get("/api/turn", read_turn)
    app.router.add_post("/api/word", tap_word)
    app.router.add_post("/api/word/remove", untap_word)
