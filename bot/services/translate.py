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
    """Deliberately without length limits.

    An earlier version capped every field, and a model writing one word too
    many in `note_ru` failed validation — which returned *nothing at all*, so a
    perfectly good translation became "не смог перевести". Validation is for
    shape; length is this module's problem, enforced by `_tidy` below where it
    can trim instead of reject.
    """

    lemma: str = Field(default="")
    translation_ru: str = Field(default="")
    pos: str = Field(default="other")
    note_ru: str = Field(default="")


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


# The configured chat model is a reasoning model: it spends tokens thinking
# before it writes anything. The first version of this allowed 200, which the
# reasoning alone could exhaust — the JSON then came back empty or truncated
# and every tap answered "не смог перевести". The assessor next door was always
# allowed 2000; a dictionary lookup is not the place to economise.
LOOKUP_TOKENS = 1000

# A plain-text second attempt, for when structured output is unavailable or the
# model simply will not produce the shape. Looking a word up should not depend
# on JSON mode being in a good mood.
PLAIN_SYSTEM = """Translate one English word into Russian for a learner.

Reply with exactly two lines and nothing else:
line 1: the dictionary form of the word in English
line 2: its Russian translation as used in the given sentence (1-3 words)"""


def _tidy(sense: WordSense, word: str) -> WordSense | None:
    """Trim to what the database columns hold, or reject an empty answer."""
    translation = sense.translation_ru.strip().strip('"«»')
    if not translation:
        return None

    # A model asked for a lemma sometimes returns the inflected form anyway;
    # falling back to the tapped word is better than an empty card.
    sense.lemma = (sense.lemma.strip() or word.strip()).lower()[:64]
    sense.translation_ru = translation[:128]
    sense.pos = (sense.pos or "other").strip()[:16]
    sense.note_ru = sense.note_ru.strip()[:120]
    return sense


async def _structured(word: str, context: str) -> WordSense | None:
    sense, _usage = await llm.get_backend().complete_json(
        system=SYSTEM,
        prompt=_prompt(word, context),
        schema=WordSense,
        max_tokens=LOOKUP_TOKENS,
    )
    return None if sense is None else _tidy(sense, word)


async def _plain(word: str, context: str) -> WordSense | None:
    """Two lines of text. Every model can do this; not every one does JSON."""
    reply, _usage = await llm.get_backend().complete(
        system=PLAIN_SYSTEM,
        messages=[{
            "role": "user",
            "content": f'Word: "{word.strip()}"\nSentence: "{(context or word).strip()[:400]}"',
        }],
        max_tokens=LOOKUP_TOKENS,
    )
    lines = [line.strip(" -•\t") for line in (reply or "").splitlines() if line.strip()]
    if not lines:
        return None
    # One line back means it answered with the translation alone.
    lemma, translation = (lines[0], lines[1]) if len(lines) >= 2 else (word, lines[0])
    return _tidy(WordSense(lemma=lemma, translation_ru=translation), word)


# A plain dictionary, free and keyless, as the floor under both model attempts.
# It knows nothing about the sentence — "run" comes back as one of its forty
# meanings rather than the one in front of the learner — which is exactly why
# it is last and not first. But a mediocre translation beats the blank that
# every tap was returning.
MYMEMORY_API = "https://api.mymemory.translated.net/get"

# MyMemory answers 200 with its complaints in the translation field, shouted.
_A_COMPLAINT = re.compile(r"^[A-Z0-9 ,.'\"!:;-]{12,}$")


async def _dictionary(word: str, context: str) -> WordSense | None:
    import httpx

    async with httpx.AsyncClient(timeout=8.0) as http:
        response = await http.get(
            MYMEMORY_API, params={"q": word.strip(), "langpair": "en|ru"}
        )
        response.raise_for_status()
        data = response.json()

    if int(data.get("responseStatus", 0)) != 200:
        return None
    translation = ((data.get("responseData") or {}).get("translatedText") or "").strip()
    # Quota notices and usage errors arrive in the same field as translations.
    if not translation or _A_COMPLAINT.match(translation):
        return None

    return _tidy(WordSense(lemma=word, translation_ru=translation, pos="other"), word)


async def look_up(word: str, *, context: str = "") -> WordSense | None:
    """Translate `word` as used in `context`, or None if nothing would answer.

    Three attempts, best first: the model with the sentence, the model without
    the shape requirement, then a plain dictionary. Quality degrades down the
    list and reliability climbs, which is the right way round — the failure
    being fixed here is taps that answered nothing at all.

    Never raises. A tap that produces nothing should cost the learner a shrug,
    not an error message in the middle of a lesson.
    """
    if not is_a_word(word):
        return None

    for attempt in (_structured, _plain, _dictionary):
        try:
            sense = await attempt(word, context)
        except Exception:  # noqa: BLE001 - one tap must never break the reader
            logger.exception("translation failed for %r via %s", word, attempt.__name__)
            continue
        if sense is not None:
            return sense

    logger.warning("no translation for %r", word)
    return None


def as_json(sense: WordSense) -> str:
    return json.dumps(sense.model_dump(), ensure_ascii=False)
