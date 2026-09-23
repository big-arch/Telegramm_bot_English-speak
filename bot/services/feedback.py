"""Which corrections actually reach the learner.

This is the pedagogy, and it lives in code rather than in a prompt so it can be
tested and tuned without re-prompting a model.

Correcting everything is the default failure of an LLM tutor. It exceeds working
memory, it demotivates, and learners cannot act on eight simultaneous
instructions. At most three corrections per debrief, chosen by:

1. severity — anything that broke comprehension
2. level readiness — errors in structures the learner is ready to fix
3. systematicity — a recurring error beats a one-off slip

Everything else is dropped silently. A learner who was understood should feel
understood.
"""

from __future__ import annotations

import html
import re
from collections import Counter

from bot.services.llm import Finding

MAX_CORRECTIONS = 3

_SEVERITY_WEIGHT = {"blocking": 100, "noticeable": 40, "minor": 10}

_LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

# The level at which each structure becomes worth correcting. Flagging the
# present perfect to someone who has never met it teaches nothing — it just
# tells them they are wrong about something they had no way to get right.
_CATEGORY_READY_AT = {
    "article": "A1",
    "agreement": "A1",
    "plural_countability": "A1",
    "word_order": "A2",
    "preposition": "A2",
    "tense_aspect": "A2",
    "word_choice": "A2",
    "word_form": "B1",
    "modality": "B1",
    "conditional": "B1",
    "register": "B2",
    "pronunciation": "A1",
}


def _level_index(level: str) -> int:
    try:
        return _LEVEL_ORDER.index(level)
    except ValueError:
        return 1


def _is_ready(category: str, level: str) -> bool:
    ready_at = _CATEGORY_READY_AT.get(category, "A2")
    return _level_index(level) >= _level_index(ready_at)


def score(finding: Finding, level: str, recent_counts: Counter[str]) -> float:
    base = _SEVERITY_WEIGHT.get(finding.severity, 10)
    if not _is_ready(finding.category, level):
        # Not suppressed entirely — a blocking error still surfaces — but it
        # loses to anything the learner can actually act on.
        base *= 0.25
    # Systematic beats incidental. A slip self-corrects; a pattern is a gap in
    # the learner's interlanguage and is worth the correction budget.
    base += min(recent_counts.get(finding.category, 0), 5) * 8
    return base


def select(
    findings: list[Finding],
    *,
    level: str,
    recent_counts: Counter[str] | None = None,
    limit: int = MAX_CORRECTIONS,
) -> list[Finding]:
    counts = recent_counts or Counter()
    ranked = sorted(findings, key=lambda f: score(f, level, counts), reverse=True)

    # One correction per category: three article corrections read as nagging,
    # and the learner takes away no more than one of them anyway.
    seen: set[str] = set()
    picked: list[Finding] = []
    for finding in ranked:
        if finding.category in seen:
            continue
        seen.add(finding.category)
        picked.append(finding)
        if len(picked) >= limit:
            break
    return picked


CATEGORY_RU = {
    "article": "артикли",
    "tense_aspect": "времена",
    "agreement": "согласование",
    "preposition": "предлоги",
    "word_order": "порядок слов",
    "word_choice": "выбор слова",
    "word_form": "форма слова",
    "plural_countability": "число и исчисляемость",
    "modality": "модальные глаголы",
    "conditional": "условные предложения",
    "register": "стиль речи",
    "pronunciation": "произношение",
}


def render(findings: list[Finding]) -> str:
    """Format selected corrections for the debrief message.

    One quote block per correction, so each reads as its own card rather than
    three lines lost in a column of text. Everything the model wrote is
    escaped: the span is quoted from the learner, the correction and the
    explanation are generated, and any of them can contain "&" or "<" — which
    in an HTML message makes Telegram reject the whole debrief.
    """
    if not findings:
        return "Ошибок, которые стоило бы разбирать, не было. Так и держи 👏"

    blocks = []
    for finding in findings:
        tag = html.escape(CATEGORY_RU.get(finding.category, finding.category), quote=False)
        blocks.append(
            "<blockquote>"
            f"<b>{tag}</b>\n"
            f"<s>{html.escape(finding.original_span, quote=False)}</s> → "
            f"<b>{html.escape(finding.correction, quote=False)}</b>\n"
            f"<i>{html.escape(finding.explanation, quote=False)}</i>"
            "</blockquote>"
        )
    return "\n".join(blocks)


def hint_for(finding: Finding) -> str:
    """A prompt instead of an answer.

    Giving the correction outright is a fact the learner reads. Making them
    produce it turns the correction into a retrieval, and retrieval is what
    actually builds memory. This is the single cheapest pedagogical upgrade in
    the product.
    """
    tag = CATEGORY_RU.get(finding.category, finding.category)
    return (
        f"Почти. Здесь что-то не так — посмотри на «{finding.original_span}».\n"
        f"Подсказка: {tag}.\n\n"
        f"Попробуешь ещё раз?"
    )


# --------------------------------------------------------------------------- #
# "How a native speaker would say it"
# --------------------------------------------------------------------------- #

_WORDS = re.compile(r"[a-z']+")


def _shape(text: str) -> list[str]:
    """The words, without the case and punctuation that speech-to-text invents."""
    return _WORDS.findall((text or "").lower().replace("’", "'"))


def native_rewrite(utterance: str, rewritten: str | None) -> str | None:
    """The assessor's natural version of what they said, when it is worth showing.

    Shown hidden under a spoiler, never inline: the rule of this product is
    that nobody is interrupted with corrections mid-conversation, and a
    spoiler is a correction you have to ask for. None when there is nothing to
    ask for — a rewrite that differs only in a comma or a capital letter is
    the assessor tidying transcription noise, and showing it would teach the
    learner that they made a mistake they did not make.
    """
    rewritten = (rewritten or "").strip()
    if not rewritten or len(rewritten) > 400:
        return None
    if _shape(rewritten) == _shape(utterance):
        return None
    return rewritten
