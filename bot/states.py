"""FSM states.

Deliberately minimal: only onboarding lives in FSM. Conversation state lives in
the database, so a restart loses nothing a learner would notice — which is also
why MemoryStorage is acceptable here when Redis is not configured.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    choosing_level = State()
    choosing_persona = State()
    choosing_goal = State()


class Reviewing(StatesGroup):
    answering = State()
