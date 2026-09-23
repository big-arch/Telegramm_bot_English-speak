"""Running a scenario: telling the partner the scene, and noticing goals met.

The partner and the checker are separate calls on purpose. A model asked to
play a barista *and* grade the customer does both badly — it starts steering
the scene towards the checklist, and "so, would you like to pay by card?" is a
barista doing the learner's task for them. The partner is told the goals only
so it can leave room for them; deciding whether one was met is someone else's
job, run concurrently so it costs no waiting.

The checker is strict in one direction only. A goal is marked when the
learner's own words do the thing — not when the partner does it for them, not
when it is merely implied. A checklist that ticks itself teaches the learner
that the checklist is decoration.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from bot.scenarios import Scenario
from bot.services import llm

logger = logging.getLogger(__name__)


def partner_brief(scenario: Scenario, done: set[int]) -> str:
    """The scene, for the tutor's system prompt."""
    open_goals = [g.check for i, g in enumerate(scenario.goals) if i not in done]
    lines = [
        "ROLE-PLAY. This conversation is a scene, not a chat.",
        f"You are playing: {scenario.role}. Stay in that role the whole time — "
        "your name and personality stay yours, your situation is the scene's.",
        f"The scene: {scenario.setting}",
        "The learner is practising real-life English. Behave exactly as that "
        "person would: ask what they would ask, react how they would react, "
        "and add one small realistic complication if the scene goes too "
        "smoothly (an item is out of stock, a form needs a detail, a follow-up "
        "question).",
    ]
    if open_goals:
        lines.append(
            "Things the learner still needs to manage to do — make natural room "
            "for them, but NEVER do them on the learner's behalf and never "
            "list them: " + "; ".join(open_goals) + "."
        )
    else:
        lines.append(
            "The learner has done everything the scene asked of them. Bring the "
            "scene to a warm, natural close in one or two lines, in role."
        )
    return "\n".join(lines)


class GoalCheck(BaseModel):
    met: list[int] = Field(default_factory=list)


CHECK_SYSTEM = """You judge whether an English learner, in a role-play, has just \
achieved specific goals WITH THEIR OWN WORDS.

You get the partner's last line, the learner's new utterance, and a numbered list \
of goals not yet achieved. Return the numbers of the goals that the learner's \
utterance itself accomplishes.

Rules:
- Only the learner's utterance counts. If the partner did it, it is not met.
- It must actually be done, not planned or implied. "I want coffee" orders a drink \
but does not state a size.
- Grammar mistakes do NOT matter. A broken sentence that clearly does the thing \
counts. This is about communication, not accuracy.
- When unsure, leave it out.

Answer in JSON only: {"met": [numbers]}"""


async def check_goals(
    scenario: Scenario, done: set[int], *, partner_line: str, utterance: str
) -> set[int]:
    """Goal indices newly met by this utterance. Empty on any failure — a goal
    missed this turn can be met next turn; one ticked wrongly cannot be unticked
    in the learner's mind."""
    open_goals = [(i, g) for i, g in enumerate(scenario.goals) if i not in done]
    if not open_goals or not utterance.strip():
        return set()

    listing = "\n".join(f"{i}. {g.check}" for i, g in open_goals)
    prompt = (
        f'Partner\'s last line: "{partner_line.strip()[:400]}"\n'
        f'Learner said: "{utterance.strip()[:600]}"\n\n'
        f"Goals not yet achieved:\n{listing}\n\n"
        'JSON: {"met": [...]}'
    )
    try:
        result, _usage = await llm.get_backend().complete_json(
            system=CHECK_SYSTEM, prompt=prompt, schema=GoalCheck, max_tokens=600
        )
    except Exception:  # noqa: BLE001 - a missed tick is the harmless failure
        logger.exception("goal check failed for %s", scenario.key)
        return set()

    if result is None:
        return set()
    valid = {i for i, _ in open_goals}
    return {i for i in result.met if i in valid}
