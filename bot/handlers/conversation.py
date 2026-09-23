"""The core loop: talk, listen, reply, remember.

Everything here is arranged around one constraint — a learner who waits with no
feedback assumes it broke and sends again, which doubles the load and the bill.
So: acknowledge immediately, do the work, edit the acknowledgement into the
result.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from bot import personas as personas_mod
from bot.callbacks import HintCB, TopicCB
from bot.config import settings
from bot.db.models import ErrorRecord, Session, Topic, Turn, User
from bot.db.repositories import ErrorRepo, SessionRepo, TopicRepo, TurnRepo, UsageRepo
from bot.keyboards.common import opening_kb, reader_kb, topics_kb
from bot.services import conversation as convo_service
from bot.services import feedback, fluency, hints, images, llm, portraits, stt, vision, wellbeing
from bot.services.speak import send_spoken
from bot.texts import (
    CHOOSE_TOPIC,
    CRISIS_HELP,
    DAILY_LIMIT_REACHED,
    DEBRIEF_HEADER,
    ERROR_GENERIC,
    LISTENING,
    LOOKING,
    NO_ACTIVE_SESSION,
    PHOTO_NOT_FOUND,
    PHOTO_NOT_READABLE,
    PHOTO_NOT_SUPPORTED,
    PHOTO_TOO_BIG,
    SEND_VOICE_NOT_FILE,
    SESSION_TOO_SHORT,
    THINKING,
    TRANSCRIBE_FAILED,
    VOICE_TOO_LONG,
)

logger = logging.getLogger(__name__)
router = Router(name="conversation")

MIN_TURNS_FOR_DEBRIEF = 2


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _topic_of(session: DbSession, convo: Session) -> Topic | None:
    if convo.topic_id is None:
        return None
    return await session.get(Topic, convo.topic_id)


# --------------------------------------------------------------------------- #
# Starting a conversation
# --------------------------------------------------------------------------- #


@router.message(Command("talk"))
async def cmd_talk(message: Message, session: DbSession, user: User) -> None:
    topics = await TopicRepo(session).for_level(user.productive_level)
    if not topics:
        await message.answer(
            "Темы ещё не загружены. Запусти <code>python -m scripts.seed</code> и попробуй снова."
        )
        return
    await message.answer(CHOOSE_TOPIC, reply_markup=topics_kb(topics))


@router.callback_query(TopicCB.filter())
async def start_topic(
    query: CallbackQuery,
    callback_data: TopicCB,
    session: DbSession,
    user: User,
    bot: Bot,
) -> None:
    await query.answer()

    topic = await session.get(Topic, callback_data.topic_id)
    if topic is None or not isinstance(query.message, Message):
        return

    convo = await SessionRepo(session).start(
        user_id=user.id, persona_key=user.persona_key, topic_id=topic.id
    )
    convo.opening_line = topic.opening_line
    await session.commit()

    persona = personas_mod.get(user.persona_key)
    header = (
        f"{topic.emoji} <b>{topic.title_ru}</b>\n"
        f"Говоришь с {persona.emoji} {persona.name}\n\n"
        f"<i>Закончить и получить разбор — /finish</i>"
    )
    # Every conversation opens on who you are talking to. The topic list is
    # replaced rather than left above it, so the chat reads as a scene rather
    # than a menu with a scene underneath.
    if await portraits.send(bot, query.message.chat.id, persona, caption=header):
        await query.message.delete()
    else:
        await query.message.edit_text(header)
    await send_spoken(
        bot,
        session,
        chat_id=query.message.chat.id,
        text=topic.opening_line,
        persona=persona,
        level=user.productive_level,
        caption=topic.opening_line,
        reply_markup=opening_kb(),
    )


@router.callback_query(HintCB.filter())
async def give_hint(
    query: CallbackQuery,
    callback_data: HintCB,
    session: DbSession,
    user: User,
) -> None:
    """Three ways to answer the line this button sits under."""
    if not isinstance(query.message, Message):
        await query.answer()
        return

    if callback_data.turn_id == 0:
        # The opening line of the conversation in progress — not a turn yet.
        convo = await SessionRepo(session).active_for(user.id)
        line = convo.opening_line if convo else None
        cache_key = -convo.id if convo else 0
    else:
        turn = await session.get(Turn, callback_data.turn_id)
        # Callback data is client-supplied; the id in it proves nothing on its
        # own, so a turn that is not theirs is treated as one that is not there.
        line = turn.assistant_text if turn and turn.user_id == user.id else None
        cache_key = callback_data.turn_id

    if not line:
        await query.answer()
        return

    # Acknowledged straight away: generating takes a couple of seconds, and a
    # button that does nothing for two seconds gets pressed again.
    await query.answer("💡 Думаю, как можно ответить…")

    suggestions = await hints.suggest(cache_key, line, user.productive_level)
    if not suggestions:
        await query.message.answer(
            "Не получилось придумать варианты 😕 Попробуй ответить хоть одним словом — "
            "это тоже ответ, и с него легко продолжить."
        )
        return

    await query.message.answer(
        hints.render(suggestions, with_russian=user.productive_level in {"A1", "A2"})
    )


async def _ensure_session(session: DbSession, user: User) -> Session:
    """Get the open conversation, or open a free-talk one.

    Someone who just starts talking should not be told to press a button first.
    """
    repo = SessionRepo(session)
    convo = await repo.active_for(user.id)
    if convo is not None:
        return convo

    topic = await TopicRepo(session).by_slug("free_talk")
    convo = await repo.start(
        user_id=user.id,
        persona_key=user.persona_key,
        topic_id=topic.id if topic else None,
    )
    if topic:
        convo.opening_line = topic.opening_line
        await session.commit()
    return convo


async def _reply(
    bot: Bot,
    session: DbSession,
    *,
    chat_id: int,
    convo: Session,
    user: User,
    text: str,
    photo_query: str | None = None,
    turn_id: int | None = None,
) -> None:
    """Send the tutor's turn: the picture first, then the voice.

    Order matters. The photo arrives while the speech is still being
    synthesised, so the learner is already looking at it when the voice starts
    — which is how a person shows you something.
    """
    if photo_query:
        sent = False
        url = await images.find(photo_query)
        if url:
            try:
                await bot.send_photo(chat_id, url)
                sent = True
            except TelegramAPIError:
                # Telegram fetches the URL itself and sometimes refuses one.
                logger.info("could not send photo for %r", photo_query)
        if not sent:
            # We only get here having decided a picture was owed, which means
            # the tutor has probably just said one was coming. Saying nothing
            # makes it look broken; owning it turns the miss into the better
            # exercise — they describe it instead.
            await bot.send_message(chat_id, PHOTO_NOT_FOUND)

    persona = personas_mod.get(convo.persona_key)
    await send_spoken(
        bot,
        session,
        chat_id=chat_id,
        text=text,
        persona=persona,
        level=user.productive_level,
        caption=text,
        # Every reply is a text they can now take apart word by word.
        reply_markup=reader_kb(turn_id) if turn_id else None,
    )


def _heard(text: str, result: convo_service.TurnResult | None = None) -> str:
    """The transcript line, with the native version hidden under it if there is one.

    Escaped, always. Speech-to-text writes "rock & roll" and "x < y" like any
    other text, and an unescaped ampersand in an HTML message makes Telegram
    reject the edit — which surfaced as the whole turn failing.

    The native version is withheld on a turn that carried feeling: nobody who
    has just said they lost their job should find a grammar note under it.
    """
    line = f"🗣 <i>{html.escape(text)}</i>"
    if result is None or result.assessment is None:
        return line
    if wellbeing.read(text).needs_care:
        return line
    better = feedback.native_rewrite(text, result.assessment.rewritten)
    if better:
        line += f"\n✨ Как сказал бы носитель: <tg-spoiler>{html.escape(better)}</tg-spoiler>"
    return line


async def _crisis_handled(message: Message, user: User, text: str) -> bool:
    """Stop everything if this is not a language lesson any more.

    Checked in code rather than left to the model, and checked before the model
    is called at all. Everything else in this project that had to work was
    eventually moved out of the prompt for the same reason — a free-tier model
    dropping an instruction is a bug everywhere and unacceptable here.

    The reply is in Russian because it has to land without being parsed, and it
    names no helpline this repository cannot vouch for: a wrong number given to
    someone in that state is worse than none. CRISIS_CONTACT adds the right
    local one.
    """
    if not wellbeing.read(text).crisis:
        return False

    logger.warning("crisis language from user %s — lesson stopped", user.tg_id)
    body = CRISIS_HELP
    if settings.crisis_contact:
        body = f"{body}\n\n{settings.crisis_contact}"
    await message.answer(body)
    return True


# --------------------------------------------------------------------------- #
# Voice — the main path
# --------------------------------------------------------------------------- #


@router.message(F.voice)
async def on_voice(message: Message, session: DbSession, user: User, bot: Bot) -> None:
    voice = message.voice
    assert voice is not None

    # Guard before downloading, with a human refusal rather than a late failure.
    if voice.duration > settings.max_voice_seconds:
        await message.answer(VOICE_TOO_LONG.format(limit=settings.max_voice_seconds))
        return

    if settings.free_daily_turns:
        used = await UsageRepo(session).voice_turns_today(user.id, _today())
        if used >= settings.free_daily_turns:
            await message.answer(DAILY_LIMIT_REACHED.format(limit=settings.free_daily_turns))
            return

    status = await message.answer(LISTENING)

    try:
        file = await bot.get_file(voice.file_id)
        buffer = await bot.download_file(file.file_path)
        audio = buffer.read() if buffer is not None else b""
    except Exception:
        logger.exception("voice download failed for user %s", user.tg_id)
        await status.edit_text(ERROR_GENERIC)
        return

    transcript = await stt.transcribe(audio, filename=f"{voice.file_unique_id}.ogg")
    if transcript is None or transcript.is_empty:
        await status.edit_text(TRANSCRIBE_FAILED)
        return

    metrics = fluency.compute(transcript.words, transcript.duration or voice.duration)

    # Show the transcript straight away: it is the fastest, cheapest feedback
    # there is, and it tells the learner what was actually heard.
    await status.edit_text(f"{_heard(transcript.text)}\n\n{THINKING}")

    if await _crisis_handled(message, user, transcript.text):
        await status.edit_text(_heard(transcript.text))
        return

    convo = await _ensure_session(session, user)
    topic = await _topic_of(session, convo)

    try:
        result = await convo_service.process_turn(
            session,
            user=user,
            convo=convo,
            topic=topic,
            text=transcript.text,
            modality="voice",
            metrics=metrics,
        )
    except Exception:
        logger.exception("turn processing failed for user %s", user.tg_id)
        await status.edit_text(ERROR_GENERIC)
        return

    await status.edit_text(_heard(transcript.text, result))
    await _reply(
        bot, session, chat_id=message.chat.id, convo=convo, user=user,
        text=result.reply, photo_query=result.photo_query, turn_id=result.turn.id,
    )


# --------------------------------------------------------------------------- #
# Photos — the learner shows you something
# --------------------------------------------------------------------------- #


@router.message(F.photo)
async def on_photo(message: Message, session: DbSession, user: User, bot: Bot) -> None:
    """A picture sent the ordinary way: compressed, as a photo."""
    photo = message.photo[-1] if message.photo else None
    if photo is None:
        return
    await _talk_about_photo(
        message, session, user, bot,
        file_id=photo.file_id, size=photo.file_size or 0, mime="image/jpeg",
    )


@router.message(F.document.mime_type.startswith("image/"))
async def on_image_document(
    message: Message, session: DbSession, user: User, bot: Bot
) -> None:
    """A picture sent as a file, which is not an edge case at all.

    Desktop Telegram sends a dragged-in image as a document by default, and
    "send without compression" does the same on every client. Those updates
    carry no `photo` field, so they fell through to the wrong-media handler and
    were answered with "that's a file, not a voice message" — which is why the
    bot looked like it could not see photographs while vision was working
    perfectly.
    """
    document = message.document
    if document is None:
        return
    await _talk_about_photo(
        message, session, user, bot,
        file_id=document.file_id,
        size=document.file_size or 0,
        mime=document.mime_type or "image/jpeg",
    )


async def _talk_about_photo(
    message: Message,
    session: DbSession,
    user: User,
    bot: Bot,
    *,
    file_id: str,
    size: int,
    mime: str,
) -> None:
    """Talk about a picture the learner sent, however they sent it.

    Describing an image is a speaking skill in its own right, and doing it on
    their own photo rather than a stock one is the difference between an
    exercise and a conversation — they already know what is in it and want to
    say something about it.
    """
    if not vision.available():
        # A tutor who cannot see can still ask them to describe it, which is
        # the better exercise anyway. Never a dead end.
        await message.answer(PHOTO_NOT_SUPPORTED)
        return

    # An uncompressed photo off a modern phone is routinely larger than any
    # vision API will take. Said before the download rather than after, and
    # with the one action that fixes it.
    if size and size > settings.max_photo_bytes:
        await message.answer(PHOTO_TOO_BIG.format(mb=size / 1_000_000))
        return

    status = await message.answer(LOOKING)

    try:
        file = await bot.get_file(file_id)
        buffer = await bot.download_file(file.file_path)
        image = buffer.read() if buffer is not None else b""
    except Exception as exc:  # noqa: BLE001 - the reason is worth showing
        logger.exception("photo download failed for user %s", user.tg_id)
        await status.edit_text(
            f"{ERROR_GENERIC}\n\n<code>download: {type(exc).__name__}: {exc}</code>"
        )
        return

    description, _usage, notes = await vision.describe(image, mime=mime)
    if not description:
        # Every provider had its own reason and none of them reach the learner
        # as a log line. Showing them is what turns "it doesn't work" into
        # something anyone can act on — the lesson from the photo-sending bug.
        logger.info("vision failed for user %s: %s", user.tg_id, "; ".join(notes))
        report = "\n".join(f"• <code>{note}</code>" for note in notes)
        await status.edit_text(f"{PHOTO_NOT_READABLE}\n\n{report}")
        return

    # A caption is usually a fragment rather than a sentence, so it is shown to
    # the tutor but not graded — marking "my dog :)" as an error would be both
    # wrong and discouraging.
    caption = (message.caption or "").strip()
    if caption:
        description = f'{description}\n\nThey wrote with it: "{caption}"'

    convo = await _ensure_session(session, user)
    topic = await _topic_of(session, convo)

    try:
        result = await convo_service.process_turn(
            session,
            user=user,
            convo=convo,
            topic=topic,
            text="",
            modality="photo",
            photo_description=description,
            image_file_id=file_id,
        )
    except Exception:
        logger.exception("photo turn failed for user %s", user.tg_id)
        await status.edit_text(ERROR_GENERIC)
        return

    await status.delete()
    await _reply(
        bot, session, chat_id=message.chat.id, convo=convo, user=user,
        text=result.reply, photo_query=result.photo_query, turn_id=result.turn.id,
    )


@router.message(F.audio | F.video_note | F.document)
async def on_wrong_media(message: Message) -> None:
    # F.voice does not match an uploaded mp3, and "why doesn't it work when I
    # send a file" is a support ticket waiting to happen.
    await message.answer(SEND_VOICE_NOT_FILE)


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, session: DbSession, user: User, bot: Bot) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    if await _crisis_handled(message, user, text):
        return

    status = await message.answer(THINKING)
    convo = await _ensure_session(session, user)
    topic = await _topic_of(session, convo)

    try:
        result = await convo_service.process_turn(
            session,
            user=user,
            convo=convo,
            topic=topic,
            text=text,
            modality="text",
        )
    except Exception:
        logger.exception("turn processing failed for user %s", user.tg_id)
        await status.edit_text(ERROR_GENERIC)
        return

    # Their own message is already on screen, so only the native version is
    # worth a line — and when there is none, the placeholder simply goes.
    shown = _heard(text, result)
    if "tg-spoiler" in shown:
        await status.edit_text(shown.split("\n", 1)[1])
    else:
        await status.delete()
    await _reply(
        bot, session, chat_id=message.chat.id, convo=convo, user=user,
        text=result.reply, photo_query=result.photo_query, turn_id=result.turn.id,
    )


# --------------------------------------------------------------------------- #
# Finishing — where the teaching actually happens
# --------------------------------------------------------------------------- #


def _metrics_of(turn: Turn) -> fluency.FluencyMetrics:
    return fluency.FluencyMetrics(
        audio_seconds=turn.audio_seconds or 0.0,
        word_count=turn.word_count or 0,
        words_per_minute=turn.words_per_minute or 0.0,
        articulation_wpm=turn.articulation_wpm or 0.0,
        pause_ratio=turn.pause_ratio or 0.0,
        pause_count=0,
        mid_clause_pauses=turn.mid_clause_pauses or 0,
        mean_run_words=turn.mean_run_words or 0.0,
    )


@router.message(Command("finish"))
async def cmd_finish(message: Message, session: DbSession, user: User) -> None:
    repo = SessionRepo(session)
    convo = await repo.active_for(user.id)
    if convo is None:
        await message.answer(NO_ACTIVE_SESSION)
        return

    turns = await repo.history(convo.id, limit=100)
    if len(turns) < MIN_TURNS_FOR_DEBRIEF:
        await repo.finish(convo, summary=None, accuracy=None, wpm=None)
        await message.answer(SESSION_TOO_SHORT)
        return

    status = await message.answer("📝 Собираю разбор…")

    # One query for every error in the session — not one per turn.
    records = list(
        await session.scalars(
            select(ErrorRecord).where(ErrorRecord.turn_id.in_([t.id for t in turns]))
        )
    )
    findings = [
        llm.Finding(
            original_span=r.original_span,
            correction=r.correction,
            category=r.category,  # type: ignore[arg-type]
            severity=r.severity,  # type: ignore[arg-type]
            explanation=r.explanation or "",
        )
        for r in records
    ]

    recent = await ErrorRepo(session).recent_categories(user.id, days=14)
    selected = feedback.select(findings, level=user.productive_level, recent_counts=recent)

    voice_turns = [t for t in turns if t.words_per_minute]
    wpm = (
        sum(t.words_per_minute or 0.0 for t in voice_turns) / len(voice_turns)
        if voice_turns
        else None
    )
    scored = [t.accuracy_score for t in turns if t.accuracy_score is not None]
    accuracy = sum(scored) / len(scored) if scored else None

    # Progress against their own past, never against a native baseline.
    progress_line = None
    if voice_turns:
        previous = await TurnRepo(session).last_voice_turn(user.id, before_id=voice_turns[-1].id)
        if previous is not None:
            progress_line = fluency.describe_progress(
                _metrics_of(voice_turns[-1]), _metrics_of(previous)
            )

    # Roll the conversation into persistent memory. This is the step that makes
    # the next session continue rather than restart — the whole differentiator.
    topic = await _topic_of(session, convo)
    transcript: list[dict] = []
    for turn in turns:
        transcript.append({"role": "learner", "content": turn.user_text})
        transcript.append({"role": "tutor", "content": turn.assistant_text})

    try:
        memory = await llm.summarise_session(
            previous_memory=user.memory_summary,
            transcript=transcript,
            topic=topic.title_en if topic else None,
        )
        if memory:
            user.memory_summary = memory
    except Exception:
        logger.exception("memory summarisation failed for user %s", user.tg_id)

    await repo.finish(convo, summary=None, accuracy=accuracy, wpm=wpm)

    parts = [DEBRIEF_HEADER, "", f"Реплик: <b>{len(turns)}</b>"]
    if wpm:
        parts.append(f"Темп речи: <b>{wpm:.0f}</b> слов/мин")
    if progress_line:
        parts += ["", f"📈 {progress_line}"]
    parts += ["", feedback.render(selected)]
    parts += ["", "<i>Слова из этого разговора добавлены в /review.</i>"]

    await session.commit()
    await status.edit_text("\n".join(parts))
