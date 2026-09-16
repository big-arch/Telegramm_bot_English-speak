"""Orchestrates one conversational turn.

The shape that matters: the partner call and the assessor call run
**concurrently**. The learner waits for the slower of the two rather than their
sum, and if the assessor fails the conversation still continues — feedback is a
nicety, a reply is the product.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from bot import personas as personas_mod
from bot.db.models import ErrorRecord, Session, Topic, Turn, User
from bot.db.repositories import CardRepo, ErrorRepo, SessionRepo, TurnRepo, UsageRepo
from bot.services import images, llm, vision
from bot.services.backends import Usage
from bot.services.fluency import FluencyMetrics

logger = logging.getLogger(__name__)

HISTORY_TURNS = 12


@dataclass
class TurnResult:
    reply: str
    turn: Turn
    assessment: llm.Assessment | None
    # What the tutor wants to show, if anything. Resolved to a picture by the
    # handler, which owns sending.
    photo_query: str | None = None


def _build_history(convo: Session, past: list[Turn], current_text: str) -> list[dict]:
    """Messages for the Messages API. Must start with `user` and alternate."""
    history: list[dict] = []

    if convo.opening_line:
        # A truthful stand-in so the opener can sit in the assistant slot.
        history.append({"role": "user", "content": "Let's start."})
        history.append({"role": "assistant", "content": convo.opening_line})

    for turn in past:
        if turn.user_text:
            history.append({"role": "user", "content": turn.user_text})
            history.append({"role": "assistant", "content": turn.assistant_text})

    history.append({"role": "user", "content": current_text})
    return history


async def process_turn(
    db: DbSession,
    *,
    user: User,
    convo: Session,
    topic: Topic | None,
    text: str,
    modality: str,
    metrics: FluencyMetrics | None = None,
    photo_description: str | None = None,
    image_file_id: str | None = None,
) -> TurnResult:
    """One exchange.

    `photo_description` marks the turn as the learner showing a picture rather
    than saying something. The description goes into the history as context,
    and the assessor is skipped — grading the model's own description as if the
    learner had produced it would invent errors they never made.
    """
    persona = personas_mod.get(convo.persona_key)
    is_photo = photo_description is not None

    session_repo = SessionRepo(db)
    error_repo = ErrorRepo(db)

    past = await session_repo.history(convo.id, limit=HISTORY_TURNS)
    current = vision.as_history_note(photo_description) if is_photo else text
    history = _build_history(convo, past, current)

    recent = await error_repo.recent_categories(user.id)
    weak = [category for category, _ in recent.most_common(3)]

    reply_task = llm.tutor_reply(
        history=history,
        persona_character=persona.character,
        persona_accent=persona.accent,
        level=user.productive_level,
        correction_style=user.correction_style,
        memory=user.memory_summary,
        weak_categories=weak,
        topic_goal=topic.goal_prompt if topic else None,
    )
    if is_photo:
        # Nothing the learner said, so nothing to assess. Running the assessor
        # on the model's own description would manufacture errors they never
        # made and put them in their history.
        reply, reply_usage = await reply_task
        assessment, assess_usage = None, Usage()
    else:
        assess_task = llm.assess(
            utterance=text,
            level=user.productive_level,
            modality=modality,
            recent_categories=weak,
        )
        (reply, reply_usage), (assessment, assess_usage) = await asyncio.gather(
            reply_task, assess_task
        )

    # Strip the show-marker before anything stores or speaks the reply: a
    # synthesiser reading "bracket show colon brooklyn bridge" out loud is
    # worse than no picture at all.
    reply, photo_query = images.extract_request(reply)

    turn = Turn(
        session_id=convo.id,
        user_id=user.id,
        modality=modality,
        image_file_id=image_file_id,
        user_text=f"[photo] {photo_description}" if is_photo else text,
        assistant_text=reply,
        error_count=len(assessment.findings) if assessment else 0,
        estimated_level=assessment.estimated_level if assessment else None,
        lexical_range=assessment.lexical_range if assessment else None,
        grammatical_range=assessment.grammatical_range if assessment else None,
        accuracy_score=assessment.accuracy if assessment else None,
    )
    if metrics is not None:
        for column, value in metrics.as_columns().items():
            setattr(turn, column, value)

    await TurnRepo(db).add(turn)

    if assessment is not None:
        await error_repo.add_many(
            [
                ErrorRecord(
                    user_id=user.id,
                    turn_id=turn.id,
                    category=finding.category,
                    severity=finding.severity,
                    original_span=finding.original_span,
                    correction=finding.correction,
                    explanation=finding.explanation,
                )
                for finding in assessment.findings
            ]
        )
        # Words met in a real conversation make better cards than a word list.
        if assessment.new_words:
            await CardRepo(db).add_from_conversation(
                user_id=user.id,
                lemmas=assessment.new_words,
                session_id=convo.id,
                cefr=user.productive_level,
            )

    convo.turn_count += 1
    if modality == "voice":
        convo.voice_turn_count += 1

    _nudge_level(user, assessment)

    await UsageRepo(db).bump(
        user_id=user.id,
        day=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        voice_turns=1 if modality == "voice" else 0,
        text_turns=1 if modality == "text" else 0,
        audio_seconds=metrics.audio_seconds if metrics else 0.0,
        tts_characters=len(reply),
        llm_in=reply_usage.input_tokens + assess_usage.input_tokens,
        llm_out=reply_usage.output_tokens + assess_usage.output_tokens,
    )

    # One commit per unit of work: the turn, its errors, its cards and the
    # counters land together or not at all.
    await db.commit()

    return TurnResult(
        reply=reply, turn=turn, assessment=assessment, photo_query=photo_query
    )


_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def _nudge_level(user: User, assessment: llm.Assessment | None) -> None:
    """Move the level estimate slowly, on evidence.

    One utterance is noisy. A moving average over many turns is not, and it lets
    progress be visible *between* bands — sitting on "A2" for three months is
    what makes people quit.
    """
    if assessment is None:
        return

    try:
        observed = _LEVELS.index(assessment.estimated_level)
    except ValueError:
        return

    observed_score = observed * 20 + 10
    user.level_score = round(user.level_score * 0.92 + observed_score * 0.08, 2)
    band = min(int(user.level_score // 20), len(_LEVELS) - 1)
    user.productive_level = _LEVELS[band]
    # Receptive runs about a band ahead; content selection uses this.
    user.receptive_level = _LEVELS[min(band + 1, len(_LEVELS) - 1)]
