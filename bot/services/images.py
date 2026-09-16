"""Finding a photograph the tutor can show the learner.

When someone says "show me New York", a tutor who answers "I can't send
photos" has just made the conversation smaller. This module lets them send
one.

Two deliberate choices:

**Wikimedia Commons, not image generation.** Commons needs no API key, costs
nothing, and returns *real* photographs of real places. For a language lesson
that matters: "describe this street" works because the street exists, and a
learner who later sees the real place recognises it. A generated picture of
New York is a picture of nowhere.

**A marker in the reply, not function calling.** The tutor writes
`[SHOW: brooklyn bridge]` and this module resolves it. Every model can emit
text; not every model on a free tier can call functions, and the ones that can
disagree about how. The marker keeps the feature working whichever provider is
configured.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Wikimedia asks for a descriptive User-Agent and throttles anonymous clients
# that do not send one.
USER_AGENT = "SpeakOut-LanguageBot/1.0 (Telegram English tutor; contact via GitHub big-arch)"

SHOW_MARKER = re.compile(r"\[\s*SHOW\s*:\s*([^\]]{2,60})\]", re.IGNORECASE)

# Commons is full of diagrams, coats of arms and scans. None of them are what
# "show me a photo of X" means, and describing a map is a different exercise.
UNWANTED = (
    "logo", "icon", "coat of arms", "flag of", "map of", "diagram",
    "chart", "seal of", "signature", "screenshot", "poster", ".svg",
)


def extract_request(reply: str) -> tuple[str, str | None]:
    """Split a tutor reply into the text to speak and the photo to look up.

    The marker must never survive into speech — a synthesiser reading
    "bracket show colon brooklyn bridge" is worse than no picture at all.
    """
    match = SHOW_MARKER.search(reply)
    if match is None:
        return reply.strip(), None

    query = match.group(1).strip()
    cleaned = SHOW_MARKER.sub("", reply).strip()
    # Collapse the double spaces the removal tends to leave behind.
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned, query or None


# When the learner asks outright, the picture must not depend on the model
# choosing to emit a marker. Smaller free-tier models drop instructions buried
# in a long system prompt, and "show me New York" answered with "I can't send
# photos" is the exact failure this feature exists to prevent.
_ASK_PATTERNS = (
    re.compile(
        # "me" is required: "I want to show my friend the photos" is not a
        # request addressed to the tutor.
        r"\b(?:can\s+you\s+|could\s+you\s+|please\s+)?"
        r"(?:show|send)\s+me\s+"
        r"(?:a\s+|an\s+|the\s+)?(?:photo|photos|picture|pictures|image|images|pic)?\s*"
        r"(?:of\s+)?(?P<q>.+)",
        re.IGNORECASE,
    ),
    re.compile(r"\bwhat\s+(?:do|does)\s+(?P<q>.+?)\s+look\s+like", re.IGNORECASE),
    re.compile(r"\bcan\s+i\s+see\s+(?:a\s+|an\s+|the\s+)?(?P<q>.+)", re.IGNORECASE),
    # Russian, in case they slip into it — the bot still answers in English.
    re.compile(r"\bпокажи(?:те)?\s+(?:мне\s+)?(?:фото\s+)?(?P<q>.+)", re.IGNORECASE),
)

# The tutor announcing a picture is as good as asking for one. Small models
# write "Sure, here's a photo of X" and forget the marker, and a promise the
# bot does not keep reads as a broken bot — which is exactly what it is.
_PROMISE_PATTERNS = (
    re.compile(
        r"\bhere(?:'s|\s+is|\s+are)?\s+(?:a|an|the|some)?\s*"
        r"(?:photo|photos|picture|pictures|image|images|pic|shot)\s+(?:of\s+)?(?P<q>.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:this|that)\s+is\s+(?:a|an|the)?\s*"
        r"(?:photo|picture|image|pic)\s+of\s+(?P<q>.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:let\s+me\s+show\s+you|i'?ll\s+show\s+you|i\s+am\s+showing\s+you|"
        r"take\s+a\s+look\s+at)\s+(?P<q>.+)",
        re.IGNORECASE,
    ),
)

# Where a subject stops. Speech-to-text punctuates unreliably, so the trailing
# clause is also cut by hand below.
_SENTENCE_END = re.compile(r"[.!?;\n]")
_TRAILING_JUNK = re.compile(r"[\s,.!?;:]+$")
_TRAILING_CLAUSE = re.compile(
    r"\s+(?:can|could|will|would)\s+you\s+.*$|\s+(?:and|but|so)\s+.*$", re.IGNORECASE
)
_FILLER = re.compile(r"\b(?:please|pls|now|just|to\s+me|for\s+me|right\s+now)\b", re.IGNORECASE)
# Stripped uniformly rather than inside each pattern, which had them
# disagreeing about whether "the" survived. A search engine does not want it
# either.
_LEADING_ARTICLE = re.compile(r"^(?:a|an|the|some)\s+", re.IGNORECASE)


def _clean(raw: str) -> str | None:
    """Turn a captured span into something worth putting into a search box.

    The capture is greedy on purpose — it has to survive missing punctuation —
    so everything after the subject is trimmed here. "send me just ties. Can
    you do it?" has to come out as "ties", not as the whole sentence, which
    Commons answers with nothing at all.
    """
    query = _SENTENCE_END.split(raw, 1)[0]
    query = _TRAILING_CLAUSE.sub("", query)
    query = _FILLER.sub(" ", query)
    query = _TRAILING_JUNK.sub("", query).strip()
    query = _LEADING_ARTICLE.sub("", query)
    query = re.sub(r"\s{2,}", " ", query).strip(" \"'")
    # One or two stray characters are not a subject worth searching for.
    if 2 <= len(query) <= 60 and any(c.isalpha() for c in query):
        return query
    return None


def detect_request(utterance: str) -> str | None:
    """Pull a photo subject out of an explicit request, or None.

    Deliberately conservative: it fires on someone plainly asking to be shown
    something, not on any mention of a place. A spurious picture is more
    jarring than a missing one.
    """
    text = (utterance or "").strip()
    if not text or len(text) > 300:
        return None

    for pattern in _ASK_PATTERNS:
        match = pattern.search(text)
        if match is not None and (query := _clean(match.group("q"))):
            return query
    return None


def detect_promise(reply: str) -> str | None:
    """Pull the subject out of the tutor's own claim to be showing something.

    The marker is the designed path; this is the safety net under it. Once the
    tutor has written "here's a picture of X", the only acceptable outcomes are
    a picture of X or an admission — never silence.
    """
    text = (reply or "").strip()
    if not text:
        return None

    for pattern in _PROMISE_PATTERNS:
        match = pattern.search(text)
        if match is not None and (query := _clean(match.group("q"))):
            return query
    return None


# Commons is a public archive, not a curated classroom library, and the moment
# the tutor can actually deliver what it is asked for, "send me a photo of X"
# becomes a steering wheel. Two things are refused and everything else — cities,
# clothes, food, machines, anatomy in a vocabulary lesson — passes untouched:
_SEXUAL = re.compile(
    r"\b(?:nude|nudes?|naked|nudity|topless|lingerie|underwear|bikini|porn\w*|"
    r"erotic|sexy|sexual|nsfw|fetish|upskirt|cleavage|boobs?|breasts?|nipples?|"
    r"buttocks|genital\w*)\b",
    re.IGNORECASE,
)
# ...and a picture of the tutor itself. It has no body and no camera roll; a
# persona that plays along teaches the learner something false about what they
# are talking to. Note this blocks "your face", not "your city" — the persona's
# home town is a fine thing to show.
_PERSONAL = (
    r"(?:legs?|feet|foot|face|body|hair|eyes?|hands?|arms?|thighs?|stomach|"
    r"belly|chest|photos?|pictures?|selfies?)"
)
_ABOUT_THE_TUTOR = re.compile(
    rf"\byour\s+(?:own\s+)?{_PERSONAL}\b|\b(?:of|with)\s+you\b|\byourself\b|\bselfie",
    re.IGNORECASE,
)


def allowed(query: str) -> bool:
    """Whether this is a subject the tutor should go and find a photograph of."""
    return not (_SEXUAL.search(query) or _ABOUT_THE_TUTOR.search(query))


def _is_photo(title: str) -> bool:
    lowered = title.lower()
    return not any(word in lowered for word in UNWANTED)


async def _search(query: str, *, width: int = 1280) -> str | None:
    """One lookup against Commons.

    Never raises: a missing picture should cost the learner nothing but the
    picture. The conversation continues either way.
    """
    # Callers filter too; this is the backstop, so that no future path into
    # this module can reach the archive unchecked.
    if not allowed(query):
        logger.info("refusing photo lookup for %r", query)
        return None

    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": "6",  # File:
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|size",
        "iiurlwidth": str(width),
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            response = await http.get(
                COMMONS_API, params=params, headers={"User-Agent": USER_AGENT}
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        logger.exception("commons lookup failed for %r", query)
        return None

    pages = (data.get("query") or {}).get("pages") or {}
    # Search rank is in "index"; dict order is not meaningful.
    ranked = sorted(pages.values(), key=lambda p: p.get("index", 99))

    for page in ranked:
        title = page.get("title", "")
        if not _is_photo(title):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if url and url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return url

    logger.info("no usable photo found for %r", query)
    return None


# What someone says is rarely what an archive is catalogued under. "a pair of
# shiny black tights" is a sentence; "shiny black tights" is a search.
_VAGUE = {
    "a", "an", "the", "my", "your", "his", "her", "their", "our", "some",
    "pair", "of", "kind", "sort", "type", "typical", "nice", "good", "beautiful",
}


def _narrow(query: str) -> str | None:
    """A shorter query to try when the full one found nothing, or None."""
    words = query.split()
    while words and words[0].lower().strip(",.'\"") in _VAGUE:
        words.pop(0)
    narrowed = " ".join(words[-3:])
    if not narrowed or narrowed.lower() == query.lower():
        return None
    return narrowed


async def find(query: str, *, width: int = 1280) -> str | None:
    """Return a URL for a photograph of `query`, or None.

    Two attempts: the phrase as spoken, then its last few words. Learners and
    tutors describe things in sentences, and one failed search is not evidence
    that the archive has nothing.
    """
    url = await _search(query, width=width)
    if url is not None:
        return url

    shorter = _narrow(query)
    if shorter is None:
        return None
    logger.info("retrying photo lookup for %r as %r", query, shorter)
    return await _search(shorter, width=width)
