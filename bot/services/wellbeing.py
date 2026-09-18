"""Noticing how the learner is, not just what they said.

Two very different jobs live here, and keeping them apart is the whole design.

**Distress** is ordinary human weather — a bad week, a lost job, exam nerves,
"I'm so stupid, I'll never speak English". It is not an emergency and it is not
something to route around: it is the most interesting thing the learner has
said all session, and a partner who answers it with "Great! Now, the past
perfect…" is why people stop opening the app. It is flagged to the tutor, which
then leads with the person and lets the lesson follow.

**Crisis** is not that. Someone describing self-harm, suicidal intent, or abuse
is not doing a speaking exercise, and no amount of warmth from a language bot
is the help they need. The lesson stops, the reply is in their own language so
it lands instantly, and it points at real people. This one is decided **in
code**, not by asking the model to be careful — the same rule this project has
learned the hard way everywhere else: a behaviour that matters cannot depend on
a free-tier model remembering an instruction buried in a long prompt.

What this is not: a diagnosis, a therapist, or a mood score kept on file.
Nothing here labels anyone. It changes the tone of one reply, or it stops the
lesson.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Crisis
#
# Deliberately narrow. Every pattern names an act against oneself or an act of
# violence, and each is anchored so that the idioms English is full of do not
# match: "this exam is killing me", "I'm dying to see it", "I could kill for a
# coffee", "я умираю с голоду". A false positive here is not a small cost — it
# interrupts a lesson to hand someone a crisis message they did not need, which
# is both alarming and a good reason never to come back.
# --------------------------------------------------------------------------- #

_CRISIS = (
    # English: intent towards oneself.
    r"\b(?:kill|hurt|harm|cut)(?:ing)?\s+myself\b",
    r"\bend(?:ing)?\s+(?:my|it)\s+(?:life|all)\b",
    r"\b(?:want|going|plan(?:ning)?|thinking\s+about)\s+to\s+die\b",
    r"\b(?:commit|committing)\s+suicide\b",
    r"\bsuicidal\b",
    r"\bdon'?t\s+want\s+to\s+(?:live|be\s+alive)\b",
    r"\bno\s+reason\s+to\s+live\b",
    r"\bbetter\s+off\s+(?:dead|without\s+me)\b",
    # English: someone doing it to them.
    r"\b(?:he|she|they|husband|wife|partner|father|mother|dad|mum|mom)\s+"
    r"(?:hits|beats|hurts)\s+me\b",
    r"\bafraid\s+(?:of|for)\s+my\s+life\b",
    # Russian, because that is what people fall into when it is real.
    r"\bпокончить\s+с\s+собой\b",
    r"\bсамоубий\w*\b",
    r"\bсуицид\w*\b",
    r"\bне\s+хочу\s+(?:больше\s+)?жить\b",
    r"\bхочу\s+умереть\b",
    r"\b(?:убить|убью)\s+себя\b",
    r"\bрежу\s+себя\b",
    r"\bменя\s+(?:бьют|избива\w+)\b",
)

CRISIS = re.compile("|".join(_CRISIS), re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Distress
#
# Wider on purpose, and harmless when wrong: the only consequence is that the
# partner answers more gently than it strictly had to, which is never the wrong
# way to be wrong.
# --------------------------------------------------------------------------- #

_FEELINGS = (
    # How it comes out in English at A2-B2, which is to say plainly.
    r"\b(?:i'?m|i\s+am|i\s+feel|feeling)\s+(?:so\s+|really\s+|very\s+|kind\s+of\s+)?"
    r"(?:sad|depressed|anxious|scared|afraid|nervous|lonely|tired|exhausted|"
    r"burnt?\s*out|stressed|worried|angry|upset|hopeless|lost|stuck|ashamed|"
    r"embarrassed|overwhelmed)\b",
    r"\bi\s+(?:hate|can'?t\s+stand)\s+(?:my|myself|this)\b",
    r"\bi\s+(?:feel\s+)?(?:like\s+)?(?:a\s+)?(?:failure|idiot|stupid)\b",
    r"\bi'?m\s+(?:so\s+)?(?:stupid|useless|hopeless|bad\s+at)\b",
    r"\bi'?ll\s+never\b",
    r"\bnobody\s+(?:cares|understands)\b",
    r"\bi\s+gave\s+up\b",
    r"\bwant\s+to\s+(?:quit|give\s+up)\b",
    # Life events that deserve to be noticed before the grammar is.
    r"\b(?:lost|losing)\s+my\s+(?:job|mother|father|mum|mom|dad|friend)\b",
    r"\b(?:got|getting)\s+(?:fired|divorced)\b",
    r"\b(?:passed\s+away|funeral|breakup|broke\s+up)\b",
    # Russian.
    r"\bмне\s+(?:плохо|грустно|тяжело|страшно|одиноко)\b",
    r"\bя\s+(?:устал\w*|выгорел\w*|не\s+справля\w+|боюсь)\b",
    r"\bничего\s+не\s+получается\b",
    r"\bхочу\s+(?:бросить|всё\s+бросить)\b",
)

DISTRESS = re.compile("|".join(_FEELINGS), re.IGNORECASE)

# The one this product is really about. Language anxiety is the best-documented
# predictor of who stops, and it hides behind apologies for one's own English.
_LANGUAGE_ANXIETY = (
    r"\bmy\s+english\s+is\s+(?:so\s+)?(?:bad|terrible|awful|poor)\b",
    r"\bsorry\s+for\s+my\s+english\b",
    r"\bi\s+(?:can'?t|cannot)\s+speak\s+english\b",
    r"\bafraid\s+(?:to|of)\s+(?:speak|speaking|making\s+mistakes)\b",
    r"\bi\s+(?:always\s+)?make\s+(?:so\s+many|too\s+many)\s+mistakes\b",
    r"\bизвини\w*\s+за\s+(?:мой\s+)?английск\w+\b",
    r"\b(?:мой\s+)?английский\s+(?:ужасн\w+|плох\w+)\b",
    r"\bбоюсь\s+говорить\b",
)

LANGUAGE_ANXIETY = re.compile("|".join(_LANGUAGE_ANXIETY), re.IGNORECASE)


@dataclass(frozen=True)
class Reading:
    """What one utterance suggests about how the person is doing."""

    crisis: bool = False
    distress: bool = False
    language_anxiety: bool = False

    @property
    def needs_care(self) -> bool:
        return self.distress or self.language_anxiety


def read(utterance: str) -> Reading:
    text = (utterance or "").strip()
    if not text:
        return Reading()
    if CRISIS.search(text):
        # Nothing else matters about this turn, and nothing else is checked:
        # the caller stops the lesson.
        return Reading(crisis=True)
    return Reading(
        distress=bool(DISTRESS.search(text)),
        language_anxiety=bool(LANGUAGE_ANXIETY.search(text)),
    )


def guidance(reading: Reading) -> str:
    """What to tell the tutor about this turn. Empty when there is nothing to say.

    Phrased as direction for a friend, not for a clinician. The model is not
    being asked to treat anyone — it is being asked not to walk past something.
    """
    if not reading.needs_care:
        return ""

    parts = [
        "THIS TURN. They have just said something about how they are feeling. "
        "Answer the person before you answer the English. React the way a "
        "friend does: name what you heard, say something human about it, and "
        "ask one question that lets them say more if they want to. Do not "
        "correct their grammar in this reply, do not change the subject to the "
        "lesson, and do not offer advice unless they ask for it — being heard "
        "is the thing, and advice is how people stop telling you things. "
        "Never diagnose anything, and never call yourself a therapist."
    ]

    if reading.language_anxiety:
        parts.append(
            "They are apologising for their own English, which is the single "
            "most reliable sign of someone about to stop trying. Do not agree, "
            "and do not praise them emptily either — both land as pity. Point "
            "at something specific and true about what they just said (a word "
            "they chose, a structure they got right, the fact that you "
            "understood them completely), then carry on as if the apology had "
            "not happened. Mistakes are how this works and you can say so, "
            "once, lightly."
        )

    return "\n".join(parts)
