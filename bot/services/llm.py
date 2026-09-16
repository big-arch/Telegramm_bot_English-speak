"""Claude calls: the conversation partner and the assessor.

These are deliberately two separate calls with opposite instincts. A partner
wants to keep talking; an assessor wants to stop and fix. One prompt asked to do
both produces a bot that either interrupts constantly or never corrects — which
is the failure mode behind "the AI feels repetitive and shallow", the single
most common complaint about every competitor in this space.

Selection of *which* findings reach the learner happens in `tutor.py`, in code,
so the pedagogy is testable without re-prompting the model.
"""

from __future__ import annotations

import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from bot.config import settings

logger = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())

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


ASSESSOR_SYSTEM = """You analyse a single English utterance from a learner and return \
structured findings. You never speak to the learner directly.

Rules that matter more than thoroughness:

- `original_span` must appear VERBATIM in the utterance. If you cannot quote it \
exactly, omit the finding entirely. This is how the calling code verifies you did \
not invent an error.
- If the utterance is acceptable, return an empty findings list. Natural informal \
English, contractions, ellipsis and short answers are NOT errors. A learner who is \
understood should be told they were understood.
- For spoken input, ignore filler words, false starts, repetitions and \
self-corrections. Do not comment on punctuation or capitalisation — those are \
artefacts of transcription, not things the learner said.
- Report every real finding you see; the caller decides which ones to show. But do \
not dress up a stylistic preference as an error.
- `new_words` should be lemmas the learner would plausibly benefit from and did not \
already use correctly — drawn from the topic of the exchange, not from a generic list.

Rate `lexical_range` and `grammatical_range` on what was ATTEMPTED, and `accuracy` on \
whether it came out right. A learner attempting complex structures with errors is \
more advanced than one producing flawless A1 sentences; collapsing those into one \
score inverts that."""


def _tutor_system(
    *,
    persona_character: str,
    persona_accent: str,
    level: str,
    correction_style: str,
    memory: str | None,
    weak_categories: list[str],
    topic_goal: str | None,
) -> str:
    """Stable persona text first, volatile learner state last.

    Prompt caching is a prefix match, so anything that changes per user has to
    come after anything that does not. At current prompt sizes we are likely
    below the minimum cacheable prefix, but the ordering costs nothing and pays
    off the moment the persona text grows.
    """
    style_rules = {
        "soft": (
            "Correct almost nothing mid-conversation. Where the learner makes an error, "
            "recast it naturally in your own reply ('Ah, you WENT there yesterday!') and "
            "keep going. Warmth matters more than accuracy right now."
        ),
        "balanced": (
            "If an error genuinely blocks understanding, ask a natural clarification "
            "question rather than correcting. Otherwise keep going — corrections are "
            "delivered after the conversation, not during it."
        ),
        "strict": (
            "You may pause once or twice per conversation on an error that matters, and "
            "when you do, hint at it rather than giving the answer ('You ___ there "
            "yesterday?') so the learner produces the fix themselves. Never stack "
            "corrections."
        ),
    }

    parts = [
        persona_character,
        f"You speak with a {persona_accent} accent.",
        "",
        "You are having a real conversation with someone learning English. Your job is to "
        "make them talk as much as possible.",
        "",
        "How you speak:",
        f"- Keep replies to 1-3 sentences. Never lecture.",
        f"- Use vocabulary and structures at CEFR {level} or slightly above — never far "
        "above. If they would not understand a word, do not use it.",
        "- End nearly every turn with an open question that cannot be answered yes or no.",
        "- React to what they actually said. Reference it. A generic follow-up is how a "
        "conversation starts feeling like a form.",
        "- Never output emoji, stage directions, or asterisks — your text is read aloud.",
        "",
        "Corrections:",
        f"- {style_rules.get(correction_style, style_rules['balanced'])}",
        "",
        "If the learner writes in Russian, reply in simple English, and give them the "
        "English phrase they were reaching for. Do not switch to Russian yourself.",
    ]

    if topic_goal:
        parts += ["", f"Today's conversation goal: {topic_goal}"]

    # Volatile section last.
    if memory:
        parts += ["", "What you remember about this person:", memory]
    if weak_categories:
        cats = ", ".join(weak_categories)
        parts += [
            "",
            f"Their recurring weak spots are: {cats}. Create natural openings for those "
            "structures so they get practice — do not announce that you are doing this.",
        ]

    return "\n".join(parts)


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
) -> tuple[str, anthropic.types.Usage]:
    """One conversational turn. Low effort: this is chat, not reasoning work."""
    response = await client.messages.create(
        model=settings.tutor_model,
        max_tokens=400,
        system=_tutor_system(
            persona_character=persona_character,
            persona_accent=persona_accent,
            level=level,
            correction_style=correction_style,
            memory=memory,
            weak_categories=weak_categories or [],
            topic_goal=topic_goal,
        ),
        output_config={"effort": "low"},
        messages=history,
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    return text.strip(), response.usage


async def assess(
    *,
    utterance: str,
    level: str,
    modality: str,
    recent_categories: list[str] | None = None,
) -> tuple[Assessment | None, anthropic.types.Usage | None]:
    """Structured error analysis. Returns None on failure — never blocks the reply."""
    profile = [
        f"Learner CEFR level: {level}",
        "Native language: Russian",
        f"Modality: {modality}",
    ]
    if recent_categories:
        profile.append(f"Recent recurring error categories: {', '.join(recent_categories)}")

    try:
        response = await client.messages.parse(
            model=settings.assessor_model,
            max_tokens=2000,
            system=ASSESSOR_SYSTEM,
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": "\n".join(profile) + f'\n\nUtterance: "{utterance}"',
                }
            ],
            output_format=Assessment,
        )
    except anthropic.APIError:
        logger.exception("assessor call failed")
        return None, None

    assessment = response.parsed_output

    # Grounding check: drop anything the model could not quote verbatim. This
    # catches most hallucinated corrections mechanically, which is far more
    # reliable than asking the model not to hallucinate.
    if assessment is not None:
        lowered = utterance.lower()
        kept = [f for f in assessment.findings if f.original_span.lower() in lowered]
        dropped = len(assessment.findings) - len(kept)
        if dropped:
            logger.info("dropped %d ungrounded finding(s)", dropped)
        assessment.findings = kept

    return assessment, response.usage


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
    lines = [f"{t['role']}: {t['content']}" for t in transcript]
    prompt = (
        "Here is what you knew about this learner before today:\n"
        f"{previous_memory or '(nothing yet — this is your first conversation)'}\n\n"
        f"Topic of today's conversation: {topic or 'free talk'}\n\n"
        "Today's conversation:\n" + "\n".join(lines) + "\n\n"
        "Rewrite the memory note. Keep it under 120 words. Include: who they are, what "
        "they care about, what they are learning English for, concrete details they "
        "mentioned that you could naturally bring up again, and what they find hard. "
        "Drop anything that has stopped being true. Write it as notes to yourself, not "
        "as a report. Output only the note."
    )
    response = await client.messages.create(
        model=settings.tutor_model,
        max_tokens=400,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    return next((b.text for b in response.content if b.type == "text"), "").strip()
