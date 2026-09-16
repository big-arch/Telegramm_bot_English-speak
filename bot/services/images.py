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
