"""Translating one word, the way a teacher does: in the sentence it appeared in.

A dictionary gives every sense of a word and leaves the learner to guess which
one is in front of them. "Run" alone is forty meanings; "run" in *my nose is
running* is one, and it is the only one worth learning today. So the sentence
goes to the model with the word, and what comes back is the meaning **here** —
plus the dictionary form, because that is what belongs on a flashcard: meeting
"ran" should teach you "run".

Results are cached on the shared `words` row. The second learner to tap
"stubborn" pays nothing, and neither does the same learner tapping it twice.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from bot.services import llm

logger = logging.getLogger(__name__)

SYSTEM = """You are a bilingual English-Russian lexicographer helping a Russian \
speaker learn English.

You are given ONE English word or phrase and the sentence it appeared in. Return:
- lemma: the dictionary form (ran -> run, geese -> goose, was -> be). Keep \
multi-word phrases as they are.
- translation_ru: the Russian for THIS word in THIS sentence. One to three words, \
no explanations, no alternatives separated by slashes. Pick the single best fit.
- pos: one of noun, verb, adjective, adverb, preposition, phrase, other.
- note_ru: at most 8 Russian words, and ONLY when there is something a learner \
would otherwise get wrong — a false friend, an idiom, a preposition that comes \
with it. Otherwise empty.

Answer in JSON only."""


class WordSense(BaseModel):
    lemma: str = Field(default="", max_length=64)
    translation_ru: str = Field(default="", max_length=128)
    pos: str = Field(default="other", max_length=16)
    note_ru: str = Field(default="", max_length=120)


_WORDISH = re.compile(r"^[A-Za-z][A-Za-z'’\- ]{0,48}$")


def is_a_word(text: str) -> bool:
    """Whether this is worth sending to a model at all.

    The Mini App sends whatever was tapped, and a tap can land on punctuation
    or a number. Rejecting those here keeps rubbish out of the vocabulary
    catalogue, which is shared between every learner.
    """
    return bool(_WORDISH.match((text or "").strip()))


def _prompt(word: str, context: str) -> str:
    context = (context or "").strip()[:400]
    return (
        f'Word: "{word.strip()}"\n'
        f'Sentence: "{context or word.strip()}"\n\n'
        "JSON with keys: lemma, translation_ru, pos, note_ru."
    )


async def look_up(word: str, *, context: str = "") -> WordSense | None:
    """Translate `word` as used in `context`, or None if the model would not.

    Never raises. A tap that produces nothing should cost the learner a shrug,
    not an error message in the middle of a lesson.
    """
    if not is_a_word(word):
        return None

    try:
        sense, _usage = await llm.get_backend().complete_json(
            system=SYSTEM,
            prompt=_prompt(word, context),
            schema=WordSense,
            max_tokens=200,
        )
    except Exception:  # noqa: BLE001 - one tap must never break the reader
        logger.exception("translation failed for %r", word)
        return None

    if sense is None or not sense.translation_ru.strip():
        return None

    # A model asked for a lemma sometimes returns the inflected form anyway;
    # falling back to the tapped word is better than an empty card.
    sense.lemma = (sense.lemma or word).strip().lower() or word.strip().lower()
    sense.translation_ru = sense.translation_ru.strip()
    return sense


def as_json(sense: WordSense) -> str:
    return json.dumps(sense.model_dump(), ensure_ascii=False)
