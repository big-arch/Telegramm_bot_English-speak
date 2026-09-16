"""The two calls the product makes, and the schema they return.

These are deliberately two separate calls with opposite instincts. A partner
wants to keep talking; an assessor wants to stop and fix. One prompt asked to do
both produces a bot that either interrupts constantly or never corrects — which
is the failure mode behind "the AI feels repetitive and shallow", the most
common complaint about every competitor in this space.

Which model actually answers is a config switch; see bot/services/backends/.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from bot.services import prompts
from bot.services.backends import Usage, get_backend

logger = logging.getLogger(__name__)

ErrorCategory = Literal[
    "article",
    "tense_aspect",
    "agreement",
    "preposition",
    "word_order",
    "word_choice",
    "word_form",
    "plural_countability",
    "modality",
    "conditional",
    "register",
    "pronunciation",
]


class Finding(BaseModel):
    original_span: str = Field(description="Exact substring of the learner's utterance")
    correction: str = Field(description="The corrected span only, not the whole sentence")
    category: ErrorCategory
    severity: Literal["blocking", "noticeable", "minor"]
    explanation: str = Field(description="One sentence, max 20 words, plain language")


class Assessment(BaseModel):
    findings: list[Finding]
    rewritten: str = Field(description="The whole utterance, corrected and natural")
    estimated_level: Literal["A1", "A2", "B1", "B2", "C1", "C2"]
    lexical_range: int = Field(ge=0, le=100)
    grammatical_range: int = Field(ge=0, le=100)
    accuracy: int = Field(ge=0, le=100)
    new_words: list[str] = Field(
        default_factory=list,
        description="Up to 3 useful lemmas from this exchange worth learning",
    )


async def tutor_reply(
    *,
    history: list[dict],
    persona_character: str,
    persona_accent: str,
    level: str,
    correction_style: str,
    memory: str | None = None,
    weak_categories: list[str] | None = None,
    topic_goal: str | None = None,
) -> tuple[str, Usage]:
    system = prompts.tutor_system(
        persona_character=persona_character,
        persona_accent=persona_accent,
        level=level,
        correction_style=correction_style,
        memory=memory,
        weak_categories=weak_categories or [],
        topic_goal=topic_goal,
    )
    return await get_backend().complete(system=system, messages=history, max_tokens=400)


async def assess(
    *,
    utterance: str,
    level: str,
    modality: str,
    recent_categories: list[str] | None = None,
) -> tuple[Assessment | None, Usage]:
    profile = [
        f"Learner CEFR level: {level}",
        "Native language: Russian",
        f"Modality: {modality}",
    ]
    if recent_categories:
        profile.append(f"Recent recurring error categories: {', '.join(recent_categories)}")

    parsed, usage = await get_backend().complete_json(
        system=prompts.ASSESSOR_SYSTEM,
        prompt="\n".join(profile) + f'\n\nUtterance: "{utterance}"',
        schema=Assessment,
        max_tokens=2000,
    )

    assessment = parsed if isinstance(parsed, Assessment) else None

    # Grounding check: drop anything the model could not quote verbatim. This
    # catches most hallucinated corrections mechanically, which is far more
    # reliable than asking a model not to hallucinate — and it matters more on a
    # smaller free-tier model than on a frontier one.
    if assessment is not None:
        lowered = utterance.lower()
        kept = [f for f in assessment.findings if f.original_span.lower() in lowered]
        dropped = len(assessment.findings) - len(kept)
        if dropped:
            logger.info("dropped %d ungrounded finding(s)", dropped)
        assessment.findings = kept

    return assessment, usage


async def summarise_session(
    *,
    previous_memory: str | None,
    transcript: list[dict],
    topic: str | None,
) -> str:
    """Roll the conversation into the learner's persistent memory.

    This is what stops every session starting from zero. Keep it short — it is
    injected into every future system prompt, so it is a budget, not a diary.
    """
    prompt = prompts.memory_prompt(
        previous_memory=previous_memory, transcript=transcript, topic=topic
    )
    text, _ = await get_backend().complete(
        system="You keep concise notes about a language learner you tutor.",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
    )
    return text
