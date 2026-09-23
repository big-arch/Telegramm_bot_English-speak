"""Role-play scenes: a brief for the partner, a checklist for the learner.

The things worth pinning down: the catalogue is well formed, a goal is only
ever marked by the learner's own words, a failed check marks nothing, and the
last goal finishes the scene — once.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from bot import scenarios
from bot.db.base import Base, engine, sessionmaker
from bot.db.models import Session, User
from bot.services import conversation as convo_service
from bot.services import llm, roleplay
from bot.services.backends import Usage


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("scenario", scenarios.SCENARIOS, ids=lambda s: s.key)
def test_every_scene_is_complete(scenario):
    assert scenario.key and scenario.emoji and scenario.title_ru
    assert scenario.opening.strip().endswith(("?", "!", "."))
    assert 2 <= len(scenario.goals) <= 4, "a checklist, not a syllabus"
    assert set(scenario.levels) <= {"A1", "A2", "B1", "B2", "C1", "C2"}
    for goal in scenario.goals:
        assert goal.ru and goal.check


def test_keys_are_unique_and_fit_in_callback_data():
    keys = [s.key for s in scenarios.SCENARIOS]
    assert len(keys) == len(set(keys))
    # CallbackData caps the packed payload at 64 bytes.
    assert all(len(k) <= 24 for k in keys)


def test_every_level_has_something_to_play():
    for level in ("A1", "A2", "B1", "B2", "C1"):
        assert any(level in s.levels for s in scenarios.SCENARIOS), level
        assert level in scenarios.for_level(level)[0].levels, "suited ones come first"


def test_done_goals_round_trip():
    assert scenarios.parse_done(scenarios.format_done({2, 0})) == {0, 2}
    assert scenarios.parse_done(None) == set()
    assert scenarios.parse_done("") == set()


def test_the_card_fills_in():
    coffee = scenarios.get("coffee")
    blank = scenarios.card(coffee, set())
    half = scenarios.card(coffee, {0})
    full = scenarios.card(coffee, {0, 1, 2}, finished=True)

    assert blank.count("▫️") == 3 and "0 из 3" in blank
    assert half.count("✅") == 1 and "1 из 3" in half
    assert f"<s>{coffee.goals[0].ru}</s>" in half
    assert "Сценарий пройден" in full and "▫️" not in full


# --------------------------------------------------------------------------- #
# The partner's brief
# --------------------------------------------------------------------------- #


def test_the_partner_is_told_the_scene_and_what_is_left():
    coffee = scenarios.get("coffee")
    brief = roleplay.partner_brief(coffee, {0})

    assert coffee.role in brief and coffee.setting in brief
    assert coffee.goals[1].check in brief and coffee.goals[2].check in brief
    assert coffee.goals[0].check not in brief, "a met goal is not asked for again"
    assert "NEVER do them on the learner's behalf" in brief


def test_a_finished_scene_is_brought_to_a_close():
    coffee = scenarios.get("coffee")
    assert "close" in roleplay.partner_brief(coffee, {0, 1, 2})


# --------------------------------------------------------------------------- #
# The checker
# --------------------------------------------------------------------------- #


class Checker:
    def __init__(self, met):
        self.met = met
        self.prompts = []

    async def complete_json(self, *, system, prompt, schema, max_tokens):
        self.prompts.append(prompt)
        if isinstance(self.met, Exception):
            raise self.met
        return schema(met=self.met), Usage()


@pytest.mark.asyncio
async def test_only_open_goals_are_offered_and_only_open_ones_counted(monkeypatch):
    coffee = scenarios.get("coffee")
    checker = Checker([0, 1, 7])   # 0 already done, 7 does not exist
    monkeypatch.setattr(llm, "get_backend", lambda: checker)

    met = await roleplay.check_goals(
        coffee, {0}, partner_line="What can I get you?", utterance="Is there oat milk?"
    )
    assert met == {1}
    assert coffee.goals[0].check not in checker.prompts[0]


@pytest.mark.asyncio
async def test_a_failed_check_marks_nothing(monkeypatch):
    """A goal missed this turn can be met next turn; one ticked wrongly cannot
    be unticked in the learner's mind."""
    monkeypatch.setattr(llm, "get_backend", lambda: Checker(RuntimeError("quota")))
    met = await roleplay.check_goals(
        scenarios.get("coffee"), set(), partner_line="Hi", utterance="A large latte, please."
    )
    assert met == set()


@pytest.mark.asyncio
async def test_nothing_to_check_costs_nothing(monkeypatch):
    checker = Checker([0])
    monkeypatch.setattr(llm, "get_backend", lambda: checker)
    coffee = scenarios.get("coffee")

    assert await roleplay.check_goals(coffee, {0, 1, 2}, partner_line="x", utterance="y") == set()
    assert await roleplay.check_goals(coffee, set(), partner_line="x", utterance="  ") == set()
    assert checker.prompts == []


# --------------------------------------------------------------------------- #
# A whole turn
# --------------------------------------------------------------------------- #


class SceneBackend:
    """Partner, assessor and checker in one stub, telling the calls apart."""

    def __init__(self, met):
        self.met = met
        self.last_system = ""

    async def complete(self, *, system, messages, max_tokens):
        self.last_system = system
        return "Sure thing — medium or large?", Usage(10, 5)

    async def complete_json(self, *, system, prompt, schema, max_tokens):
        if schema is roleplay.GoalCheck:
            return schema(met=self.met), Usage()
        return None, Usage()   # the assessor may fail; the turn must not


@pytest_asyncio.fixture
async def scene():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as db:
        user = User(tg_id=31337, first_name="T", productive_level="A2")
        db.add(user)
        await db.flush()
        convo = Session(user_id=user.id, persona_key="emma", scenario_key="coffee",
                        goals_done="", opening_line=scenarios.get("coffee").opening)
        db.add(convo)
        await db.commit()
        yield db, user, convo
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_a_turn_in_a_scene_briefs_the_partner_and_ticks_goals(scene, monkeypatch):
    db, user, convo = scene
    backend = SceneBackend([0])
    monkeypatch.setattr(llm, "get_backend", lambda: backend)

    result = await convo_service.process_turn(
        db, user=user, convo=convo, topic=None,
        text="A large flat white, please", modality="voice",
    )

    assert "ROLE-PLAY" in backend.last_system
    assert "barista" in backend.last_system
    assert result.goals_met == (0,)
    assert result.scenario_complete is False
    assert scenarios.parse_done(convo.goals_done) == {0}


@pytest.mark.asyncio
async def test_the_last_goal_finishes_the_scene_once(scene, monkeypatch):
    db, user, convo = scene
    convo.goals_done = "0,1"
    await db.commit()

    monkeypatch.setattr(llm, "get_backend", lambda: SceneBackend([2]))
    result = await convo_service.process_turn(
        db, user=user, convo=convo, topic=None,
        text="By card, thanks a lot, bye!", modality="voice",
    )
    assert result.scenario_complete is True

    # Talking on after the end must not announce the end a second time.
    monkeypatch.setattr(llm, "get_backend", lambda: SceneBackend([0, 1, 2]))
    again = await convo_service.process_turn(
        db, user=user, convo=convo, topic=None,
        text="Have a nice day!", modality="voice",
    )
    assert again.goals_met == () and again.scenario_complete is False


@pytest.mark.asyncio
async def test_a_free_conversation_never_runs_the_checker(scene, monkeypatch):
    db, user, convo = scene
    convo.scenario_key = None
    await db.commit()

    class NoCheck(SceneBackend):
        async def complete_json(self, *, system, prompt, schema, max_tokens):
            assert schema is not roleplay.GoalCheck, "no scene, no checklist"
            return None, Usage()

    monkeypatch.setattr(llm, "get_backend", lambda: NoCheck([]))
    result = await convo_service.process_turn(
        db, user=user, convo=convo, topic=None, text="Hello there", modality="text",
    )
    assert result.goals_met == ()
