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

_TRAILING_JUNK = re.compile(r"[\s,.!?;:]+$")
_FILLER = re.compile(r"\b(?:please|pls|now|to\s+me)\b", re.IGNORECASE)
# Stripped uniformly rather than inside each pattern, which had them
# disagreeing about whether "the" survived. A search engine does not want it
# either.
_LEADING_ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)


def detect_request(utterance: str) -> str | None:
    """Pull a photo subject out of an explicit request, or None.

    Deliberately conservative: it fires on someone plainly asking to be shown
    something, not on any mention of a place. A spurious picture is more
    jarring than a missing one.
    """
    text = (utterance or "").strip()
    if not text or len(text) > 200:
        return None

    for pattern in _ASK_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        query = _FILLER.sub(" ", match.group("q"))
        query = _TRAILING_JUNK.sub("", query).strip()
        query = _LEADING_ARTICLE.sub("", query)
        query = re.sub(r"\s{2,}", " ", query).strip()
        # One or two stray words are not a subject worth searching for.
        if 2 <= len(query) <= 60 and any(c.isalpha() for c in query):
            return query
    return None


def _is_photo(title: str) -> bool:
    lowered = title.lower()
    return not any(word in lowered for word in UNWANTED)


async def find(query: str, *, width: int = 1280) -> str | None:
    """Return a URL for a photograph of `query`, or None.

    Never raises: a missing picture should cost the learner nothing but the
    picture. The conversation continues either way.
    """
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
