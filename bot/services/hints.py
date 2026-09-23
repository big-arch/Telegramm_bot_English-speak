"""Three ways to answer, for when the learner does not know what to say.

"I don't know what to say" is the most common reason a beginner's turn never
happens, and a blank pause on a voice call is exactly the moment anxiety wins.
Speak and Praktika both ship this button for that reason.

The three are deliberately graded rather than three variations of one answer:
something short they can certainly say, something ordinary, and something a
little beyond them. The third is the one that teaches — it shows the structure
they are almost ready for — and offering it beside a safe option means reaching
for it costs nothing.

They are offered as material, not as a script. The footer tells the learner to
say it their own way; reading a suggestion aloud word for word is reading
practice, and this is a speaking product.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from bot.services import llm

logger = logging.getLogger(__name__)

SYSTEM = """You help an English learner who is stuck and does not know how to reply.

You are given the last thing their conversation partner said. Suggest THREE \
replies the learner could say out loud, in natural spoken English:
1. short and easy — a few words they can certainly manage;
2. an ordinary, complete answer;
3. slightly more ambitious — one structure or phrase a little above their level.

Rules: contractions, everyday phrasing, first person, as if actually said on a \
call. Each at most 18 words. They must answer what was actually said. For each, \
give a natural Russian translation. Answer in JSON only."""


class Hint(BaseModel):
    en: str = ""
    ru: str = ""


class Hints(BaseModel):
    hints: list[Hint] = Field(default_factory=list)


_cache: dict[int, list[Hint]] = {}


def _tidy(hints: list[Hint]) -> list[Hint]:
    clean = []
    for hint in hints:
        en = re.sub(r"^\s*\d+[.)]\s*", "", hint.en).strip().strip('"')
        if en and len(en) <= 160:
            clean.append(Hint(en=en, ru=hint.ru.strip().strip('"')[:200]))
    return clean[:3]


async def _structured(line: str, level: str) -> list[Hint]:
    result, _usage = await llm.get_backend().complete_json(
        system=SYSTEM,
        prompt=(
            f"Learner's level: CEFR {level}.\n"
            f'Their partner just said: "{line.strip()[:500]}"\n\n'
            'JSON: {"hints": [{"en": "...", "ru": "..."}, ...three...]}'
        ),
        schema=Hints,
        max_tokens=1000,
    )
    return _tidy(result.hints) if result else []


async def _plain(line: str, level: str) -> list[Hint]:
    """Three lines of text, for when JSON mode will not cooperate."""
    reply, _usage = await llm.get_backend().complete(
        system="Suggest three short replies an English learner could say out loud. "
        "One per line, English only, no numbering, no commentary.",
        messages=[{
            "role": "user",
            "content": f"Level {level}. The other person said: \"{line.strip()[:500]}\"",
        }],
        max_tokens=1000,
    )
    return _tidy([Hint(en=l) for l in (reply or "").splitlines() if l.strip()])


async def suggest(turn_id: int, line: str, level: str) -> list[Hint]:
    """Three graded replies to `line`, or an empty list. Never raises.

    Cached per turn: pressing the button twice should show the same three, not
    a new set — a hint that changes when you look again is harder to use, not
    easier.
    """
    if turn_id in _cache:
        return _cache[turn_id]

    for attempt in (_structured, _plain):
        try:
            hints = await attempt(line, level)
        except Exception:  # noqa: BLE001 - a hint must never break the conversation
            logger.exception("hint generation failed via %s", attempt.__name__)
            continue
        if hints:
            if len(_cache) > 2000:
                _cache.clear()
            _cache[turn_id] = hints
            return hints
    return []


def render(hints: list[Hint], *, with_russian: bool) -> str:
    """The message body. Russian only for beginners: past A2, a translation
    beside every suggestion is a crutch that stops them reading the English."""
    import html

    lines = ["💡 <b>Можно ответить так</b>", ""]
    for number, hint in enumerate(hints, start=1):
        lines.append(f"{number}. {html.escape(hint.en, quote=False)}")
        if with_russian and hint.ru:
            lines.append(f"    <i>{html.escape(hint.ru, quote=False)}</i>")
    lines += ["", "<i>Скажи голосом и своими словами — не зачитывай дословно.</i>"]
    return "\n".join(lines)
