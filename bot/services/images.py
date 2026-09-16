"""Finding a photograph the tutor can show the learner.

When someone says "show me New York", a tutor who answers "I can't send
photos" has just made the conversation smaller. This module lets them send
one.

Three deliberate choices:

**Real archives, not image generation.** They need no API key, cost nothing,
and return *real* photographs of real places. For a language lesson that
matters: "describe this street" works because the street exists, and a learner
who later sees the real place recognises it. A generated picture of New York is
a picture of nowhere.

**Three sources, asked at once.** Wikipedia, Wikimedia Commons and Openverse
are queried concurrently and the first usable answer wins, in that order of
preference. One source being down, rate-limited, or simply ignorant of
"cheeseburger" then costs nothing — which is not a hypothetical: the single
source this started with went quiet in production and the whole feature went
with it. Concurrency keeps the cost at one round-trip rather than three.

**A marker in the reply, not function calling.** The tutor writes
`[SHOW: brooklyn bridge]` and this module resolves it. Every model can emit
text; not every model on a free tier can call functions, and the ones that can
disagree about how. The marker keeps the feature working whichever provider is
configured.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"

# Wikimedia's user-agent policy asks for an identifiable client *and a way to
# reach whoever runs it*; a vague string is one of the documented reasons for
# being refused outright.
USER_AGENT = (
    "SpeakOut-LanguageBot/1.0 "
    "(https://github.com/big-arch/Telegramm_bot_English-speak) httpx"
)

# Long enough for a slow archive, short enough that a stalled one does not hold
# up a conversation. All sources are raced, so this is the whole budget.
LOOKUP_TIMEOUT = 8.0
# Drawing a picture is not looking one up; this only ever runs when every
# archive has already come back empty, so it can afford to wait.
GENERATION_TIMEOUT = 45.0

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


def _usable(url: str | None) -> str | None:
    """Telegram fetches these URLs itself and rejects anything that is not an
    image, so the extension is checked here rather than discovered there."""
    if url and url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
        return url
    return None


# --------------------------------------------------------------------------- #
# The archives
#
# Each returns (url, detail). `detail` is a short human-readable account of what
# happened, so a failure can be reported rather than guessed at — this module
# runs somewhere with no debugger and no log access, and "nothing arrived" is
# not a diagnosis.
# --------------------------------------------------------------------------- #


async def _wikipedia(http: httpx.AsyncClient, query: str, width: int) -> tuple[str | None, str]:
    """The lead image of the best-matching article.

    First choice because an encyclopaedia has already done the editorial work:
    the picture at the top of "Hamburger" is a good hamburger, whereas an
    archive search for the word returns whatever happens to be catalogued.
    """
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrlimit": "5", "gsrnamespace": "0",
        "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": str(width),
    }
    try:
        response = await http.get(WIKIPEDIA_API, params=params)
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"failed: {type(exc).__name__} {exc}"

    for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        if not _is_photo(page.get("title", "")):
            continue
        if url := _usable((page.get("thumbnail") or {}).get("source")):
            return url, f"ok: {page.get('title')}"
    return None, f"no image on {len(pages)} article(s)"


async def _commons(http: httpx.AsyncClient, query: str, width: int) -> tuple[str | None, str]:
    """Wikimedia Commons file search — far deeper than Wikipedia, less curated."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": "6",  # File:
        "gsrlimit": "10", "prop": "imageinfo", "iiprop": "url|size",
        "iiurlwidth": str(width),
    }
    try:
        response = await http.get(COMMONS_API, params=params)
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"failed: {type(exc).__name__} {exc}"

    for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        if not _is_photo(page.get("title", "")):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        if url := _usable(info.get("thumburl") or info.get("url")):
            return url, f"ok: {page.get('title')}"
    return None, f"no usable file among {len(pages)}"


async def _openverse(http: httpx.AsyncClient, query: str, width: int) -> tuple[str | None, str]:
    """Openly-licensed photographs from across the web.

    Third because it is rate-limited for anonymous callers, but it carries
    everyday subjects — food, clothes, offices — that an encyclopaedia covers
    thinly and a language lesson needs constantly.
    """
    params = {"q": query, "page_size": "8", "mature": "false"}
    try:
        response = await http.get(OPENVERSE_API, params=params)
        response.raise_for_status()
        results = response.json().get("results") or []
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"failed: {type(exc).__name__} {exc}"

    for item in results:
        if item.get("mature"):
            continue
        if url := _usable(item.get("url")):
            return url, f"ok: {item.get('title')}"
    return None, f"no usable image among {len(results)}"


ARCHIVES = (_wikipedia, _commons, _openverse)


# --------------------------------------------------------------------------- #
# Generation — the last resort
# --------------------------------------------------------------------------- #

async def _generate(http: httpx.AsyncClient, query: str, width: int) -> tuple[str | None, str]:
    """Draw it, when no archive has it.

    Deliberately last. A real photograph is worth more in a lesson: the street
    exists, so describing it is describing something, and the learner who later
    sees it recognises it. But "a cat wearing a chef's hat" is in no archive,
    and the tutor going quiet is worse than an invented picture.

    Pollinations needs no key and no billing account, which is the whole reason
    it is here — a paid image API would put a card between the learner and a
    lesson. The URL is fetched once first: generation takes several seconds,
    and that call leaves the result cached so Telegram's own fetch is instant
    rather than a timeout.
    """
    prompt = quote(f"{query}, realistic photograph, natural light, high detail", safe="")
    url = (
        f"https://image.pollinations.ai/prompt/{prompt}"
        f"?width={width}&height={int(width * 0.75)}&nologo=true&safe=true"
    )
    try:
        response = await http.get(url, timeout=GENERATION_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return None, f"failed: {type(exc).__name__} {exc}"

    kind = response.headers.get("content-type", "")
    if not kind.startswith("image/"):
        return None, f"not an image: {kind!r}"
    return url, f"ok: generated, {len(response.content) // 1024} KB"


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


async def _race(http: httpx.AsyncClient, query: str, width: int) -> tuple[str | None, list[str]]:
    """Ask every archive at once; prefer the earliest source that answered.

    Concurrent because the learner is waiting: three sequential lookups would
    cost three round-trips to establish what one establishes. Preference order
    still decides the winner, so racing costs nothing in quality.
    """
    outcomes = await asyncio.gather(
        *(source(http, query, width) for source in ARCHIVES), return_exceptions=True
    )

    chosen, notes = None, []
    for source, outcome in zip(ARCHIVES, outcomes):
        name = source.__name__.strip("_")
        if isinstance(outcome, BaseException):
            notes.append(f"{name}: crashed: {outcome!r}")
            continue
        url, detail = outcome
        notes.append(f"{name}: {detail}")
        if chosen is None:
            chosen = url
    return chosen, notes


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=LOOKUP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


async def look_up(query: str, *, width: int = 1280) -> tuple[str | None, list[str]]:
    """Find a picture and say how it went. `find` is the ordinary way in.

    The notes are the point of this signature: this module runs somewhere with
    no debugger and no log access, and "nothing arrived" is not a diagnosis.
    """
    if not allowed(query):
        # The backstop under every caller, so that no future path into this
        # module can reach an archive — or a generator — unchecked.
        return None, [f"refused: {query!r}"]

    notes: list[str] = []
    async with _client() as http:
        # The phrase as spoken, then its last few words. Learners and tutors
        # describe things in sentences; one failed search is not evidence that
        # the archives have nothing.
        for attempt in filter(None, (query, _narrow(query))):
            url, round_notes = await _race(http, attempt, width)
            notes += [f"[{attempt}] {note}" for note in round_notes]
            if url is not None:
                return url, notes

        url, detail = await _generate(http, query, width)
        notes.append(f"generated: {detail}")
        return url, notes


async def find(query: str, *, width: int = 1280) -> str | None:
    """Return a URL for a picture of `query`, or None.

    Never raises: a missing picture should cost the learner nothing but the
    picture. The conversation continues either way.
    """
    url, notes = await look_up(query, width=width)
    logger.info("photo lookup %r -> %s | %s", query, url, "; ".join(notes))
    return url
