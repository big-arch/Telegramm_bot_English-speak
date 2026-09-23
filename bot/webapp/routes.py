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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import web
from sqlalchemy import select

from bot.db.base import sessionmaker
from bot.db.models import Turn, UsageDay, User, UserCard, Word
from bot.db.repositories import CardRepo
from bot.db.upsert import insert
from bot.services import images, srs, translate
from bot.webapp.auth import InvalidInitData, telegram_id

logger = logging.getLogger(__name__)

PAGE = Path(__file__).parent / "reader.html"
REVIEW_PAGE = Path(__file__).parent / "review.html"

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


async def _note_open(db, user: User, field: str) -> None:
    """Record that someone opened one of the Mini Apps.

    Counted at the moment the page asks for its data, which is the honest
    definition of an open: the page rendered and wanted something. Failures are
    swallowed — a counter must never be the reason a learner's app does not
    load.
    """
    try:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stmt = (
            insert(UsageDay)
            .values(user_id=user.id, day=day, **{field: 1})
            .on_conflict_do_update(
                index_elements=[UsageDay.user_id, UsageDay.day],
                set_={field: getattr(UsageDay, field) + 1},
            )
        )
        await db.execute(stmt)
        await db.commit()
    except Exception:  # noqa: BLE001 - analytics never break the product
        logger.exception("could not record a %s open", field)


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

        known = await CardRepo(db).lemmas_for(user.id, origin="tapped")
        await _note_open(db, user, "reader_opens")

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


# --------------------------------------------------------------------------- #
# Review: know it, or don't
# --------------------------------------------------------------------------- #


async def review_page(request: web.Request) -> web.Response:
    return web.Response(
        body=REVIEW_PAGE.read_bytes(),
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-cache"},
    )


async def review_queue(request: web.Request) -> web.Response:
    """The words to go through, plus how many are sitting in the archive."""
    async with sessionmaker() as db:
        user = await _learner(request, db)
        repo = CardRepo(db)
        queue = await repo.study_queue(user.id)
        archived = await repo.archived_count(user.id)
        await _note_open(db, user, "review_opens")

    return web.json_response({
        "cards": [
            {
                "id": card.id,
                "word": word.lemma,
                "translation": word.translation_ru or "",
                "image": word.image_url or "",
                "pos": word.pos if word.pos != "unknown" else "",
            }
            for card, word in queue
        ],
        "archived": archived,
    })


async def review_reveal(request: web.Request) -> web.Response:
    """The answer side of a card: translation, and a picture if one exists.

    Filled in on demand rather than up front. Most cards arrive from the
    assessor picking words out of a conversation, which stores the word and
    nothing else — so the deck is full of entries whose answer side was blank,
    which is what "I press don't know and there's no translation" was. Doing
    the work here means it costs one lookup the first time a word is missed and
    nothing ever again, instead of translating a hundred cards nobody opens.
    """
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="expected json")

    try:
        card_id = int(body.get("card", 0))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="card must be a number")

    async with sessionmaker() as db:
        user = await _learner(request, db, body)
        card = await db.get(UserCard, card_id)
        if card is None or card.user_id != user.id:
            raise web.HTTPForbidden(text="not your card")

        word = await db.get(Word, card.word_id)
        if word is None:
            raise web.HTTPForbidden(text="not your card")

        if not word.translation_ru:
            sense = await translate.look_up(word.lemma)
            if sense is not None:
                word.translation_ru = sense.translation_ru[:128]

        if word.image_url is None:
            # Generation is off for flashcards on purpose: a drawn picture of
            # "however" is a confident picture of nothing, and a wrong
            # illustration on a card you are memorising is worse than none —
            # it is the thing you end up remembering.
            found = await images.find(word.lemma, width=640, allow_generation=False)
            word.image_url = (found or "")[:500]

        translation, image = word.translation_ru or "", word.image_url or ""
        await db.commit()

    return web.json_response({"translation": translation, "image": image})


async def review_answer(request: web.Request) -> web.Response:
    """One card, answered.

    "Know" archives it; "don't know" is a lapse, which SM-2 already knows how
    to price — it does not throw the card's history away, it shortens the
    interval and brings it back sooner.
    """
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="expected json")

    try:
        card_id = int(body.get("card", 0))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="card must be a number")
    knows = bool(body.get("known"))

    async with sessionmaker() as db:
        user = await _learner(request, db, body)
        repo = CardRepo(db)

        if knows:
            if not await repo.archive(user_id=user.id, card_id=card_id):
                raise web.HTTPForbidden(text="not your card")
            await db.commit()
            return web.json_response({"archived": True})

        card = await db.get(UserCard, card_id)
        if card is None or card.user_id != user.id:
            raise web.HTTPForbidden(text="not your card")

        updated = srs.review(
            srs.CardState(
                interval_days=card.interval_days, ease=card.ease,
                reps=card.reps, lapses=card.lapses, state=card.state,
            ),
            grade=1,  # "don't know" is Again, the one grade this UI can express
        )
        card.interval_days = updated.interval_days
        card.ease = updated.ease
        card.reps = updated.reps
        card.lapses = updated.lapses
        card.state = updated.state
        card.due_at = srs.due_at(updated)
        card.last_reviewed_at = datetime.now(timezone.utc)
        await db.commit()

    return web.json_response({"archived": False})


async def review_reset(request: web.Request) -> web.Response:
    """Empty the archive: everything the learner said they knew comes back."""
    try:
        body = await request.json()
    except ValueError:
        body = {}

    async with sessionmaker() as db:
        user = await _learner(request, db, body)
        restored = await CardRepo(db).reset_archive(user.id)
        await db.commit()

    return web.json_response({"restored": restored})


# --------------------------------------------------------------------------- #
# Home: the screen behind the menu button
# --------------------------------------------------------------------------- #

HOME_PAGE = Path(__file__).parent / "home.html"
HEATMAP_DAYS = 84  # twelve weeks: long enough to show a habit, short enough to fit a phone

_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


async def home_page(request: web.Request) -> web.Response:
    return web.Response(
        body=HOME_PAGE.read_bytes(),
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-cache"},
    )


async def home_data(request: web.Request) -> web.Response:
    """Everything the home screen draws, in one request.

    One call rather than five because the screen opens from a button and is
    judged in the first half-second; a dashboard that assembles itself tile by
    tile in front of you feels slow however fast each tile is.
    """
    from sqlalchemy import func

    from bot import personas as personas_mod
    from bot.db.repositories import streak_days

    async with sessionmaker() as db:
        user = await _learner(request, db)
        cards = CardRepo(db)

        since = datetime.now(timezone.utc) - timedelta(days=HEATMAP_DAYS)
        rows = await db.execute(
            select(func.date(Turn.created_at), func.count())
            .where(Turn.user_id == user.id, Turn.created_at >= since)
            .group_by(func.date(Turn.created_at))
        )
        activity = {str(day): count for day, count in rows.all()}

        turns = await db.scalar(
            select(func.count()).select_from(Turn).where(Turn.user_id == user.id)
        ) or 0
        seconds = await db.scalar(
            select(func.coalesce(func.sum(Turn.audio_seconds), 0.0)).where(
                Turn.user_id == user.id
            )
        ) or 0.0

        learning = len(await cards.study_queue(user.id, limit=10_000))
        archived = await cards.archived_count(user.id)
        due = await cards.count_due(user.id)
        streak = await streak_days(db, user.id, user.timezone)

    # Progress inside the current band, not towards C2: "38% of the way to B2"
    # moves every week, "B1 of six levels" does not move for months, and a
    # number that does not move is a number people stop looking at.
    #
    # The band comes from the level the learner is shown, not from the score:
    # the two can disagree after a manual level change, and a ring that reads
    # "B1 -> B1" is worse than no ring.
    score = float(user.level_score or 0)
    level = user.productive_level if user.productive_level in _LEVELS else "A2"
    band = _LEVELS.index(level)
    within = 1.0 if band == len(_LEVELS) - 1 else (score - band * 20) / 20

    current = personas_mod.get(user.persona_key)
    return web.json_response({
        "name": user.first_name or "",
        "level": level,
        "next_level": _LEVELS[min(band + 1, len(_LEVELS) - 1)],
        "level_progress": round(max(0.0, min(within, 1.0)), 3),
        "streak": streak,
        "turns": turns,
        "minutes": round(float(seconds) / 60),
        "learning": learning,
        "archived": archived,
        "due": due,
        "activity": activity,
        "days": HEATMAP_DAYS,
        "persona": current.key,
        "personas": [
            {
                "key": p.key,
                "name": p.name,
                "emoji": p.emoji,
                "accent": p.accent,
                "tagline": p.tagline_ru,
                "suits": personas_mod.suits(p, user.productive_level),
            }
            for p in personas_mod.PERSONAS
        ],
    })


async def choose_persona(request: web.Request) -> web.Response:
    """Switch partner from the gallery."""
    from bot import personas as personas_mod

    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="expected json")

    key = str(body.get("key", ""))
    if key not in {p.key for p in personas_mod.PERSONAS}:
        raise web.HTTPBadRequest(text="no such partner")

    async with sessionmaker() as db:
        user = await _learner(request, db, body)
        user.persona_key = key
        # The conversation in progress keeps the partner it started with.
        # Changing voice and character mid-sentence is not a feature.
        await db.commit()

    return web.json_response({"persona": key})


async def avatar(request: web.Request) -> web.Response:
    """A partner's portrait, as SVG. Public on purpose: it is the same picture
    for everyone and carries nothing about anyone, so asking for a signature
    would only make the gallery slower to load."""
    from bot import personas as personas_mod
    from bot.webapp import avatars

    key = request.match_info["key"]
    persona = next((p for p in personas_mod.PERSONAS if p.key == key), None)
    if persona is None:
        raise web.HTTPNotFound()
    return web.Response(
        text=avatars.svg(persona.key, persona.name),
        content_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def attach(app: web.Application, *, bot_token: str) -> None:
    app["bot_token"] = bot_token
    app.router.add_get("/app", page)
    app.router.add_get("/api/turn", read_turn)
    app.router.add_post("/api/word", tap_word)
    app.router.add_post("/api/word/remove", untap_word)

    app.router.add_get("/review", review_page)
    app.router.add_get("/api/review", review_queue)
    app.router.add_post("/api/review/reveal", review_reveal)
    app.router.add_post("/api/review/answer", review_answer)
    app.router.add_post("/api/review/reset", review_reset)

    app.router.add_get("/avatar/{key}.svg", avatar)

    app.router.add_get("/home", home_page)
    app.router.add_get("/api/home", home_data)
    app.router.add_post("/api/persona", choose_persona)
