"""End-to-end test of one conversational turn against a real SQLite database.

The model is stubbed; everything else is the production path — the same
repositories, the same upserts, the same schema. This is the test that would
have caught a Postgres-only construct sneaking into the free SQLite stack.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from bot.db.base import Base, engine, sessionmaker
from bot.db.models import ErrorRecord, Session, Topic, Turn, UsageDay, User, UserCard
from bot.db.repositories import SessionRepo
from bot.services import conversation as convo_service
from bot.services import llm
from bot.services.backends import Usage
from bot.services.fluency import FluencyMetrics


class StubBackend:
    """Deterministic stand-in for Gemini/Claude."""

    name = "stub"

    def __init__(self) -> None:
        self.reply_calls = 0
        self.json_calls = 0
        self.last_system = ""

    async def complete(self, *, system, messages, max_tokens):
        self.reply_calls += 1
        self.last_system = system
        return "That sounds great. What happened next?", Usage(100, 20)

    async def complete_json(self, *, system, prompt, schema, max_tokens):
        self.json_calls += 1
        return (
            llm.Assessment(
                findings=[
                    llm.Finding(
                        original_span="I go to shop",
                        correction="I went to the shop",
                        category="tense_aspect",
                        severity="noticeable",
                        explanation="Past events take the past simple.",
                    ),
                    # Not present in the utterance — the grounding check must
                    # drop this one before it ever reaches the learner.
                    llm.Finding(
                        original_span="a completely invented phrase",
                        correction="something else",
                        category="article",
                        severity="minor",
                        explanation="Hallucinated.",
                    ),
                ],
                rewritten="I went to the shop yesterday.",
                estimated_level="B1",
                lexical_range=50,
                grammatical_range=45,
                accuracy=60,
                new_words=["grocery", "queue"],
            ),
            Usage(200, 80),
        )


@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def fixtures(db):
    user = User(tg_id=8_000_000_000, first_name="Test", productive_level="B1")
    topic = Topic(
        slug="t",
        title_en="Test",
        title_ru="Тест",
        emoji="💬",
        opening_line="How was your day?",
        goal_prompt="Get them talking about the past.",
    )
    db.add_all([user, topic])
    await db.flush()
    convo = Session(user_id=user.id, topic_id=topic.id, persona_key="emma")
    convo.opening_line = topic.opening_line
    db.add(convo)
    await db.commit()
    return user, topic, convo


@pytest.mark.asyncio
async def test_tg_id_survives_ids_above_32_bits(db):
    """Telegram ids already exceed what a plain Integer column can hold."""
    big = 7_999_999_999
    db.add(User(tg_id=big, first_name="Big"))
    await db.commit()
    found = await db.scalar(select(User).where(User.tg_id == big))
    assert found is not None and found.tg_id == big


@pytest.mark.asyncio
async def test_a_turn_persists_everything_it_should(db, fixtures, monkeypatch):
    user, topic, convo = fixtures
    stub = StubBackend()
    monkeypatch.setattr(llm, "get_backend", lambda: stub)

    metrics = FluencyMetrics(
        audio_seconds=6.0,
        word_count=12,
        words_per_minute=120.0,
        articulation_wpm=150.0,
        pause_ratio=0.2,
        pause_count=2,
        mid_clause_pauses=1,
        mean_run_words=4.0,
    )

    result = await convo_service.process_turn(
        db,
        user=user,
        convo=convo,
        topic=topic,
        text="I go to shop yesterday",
        modality="voice",
        metrics=metrics,
    )

    assert result.reply
    assert stub.reply_calls == 1 and stub.json_calls == 1

    turn = await db.scalar(select(Turn).where(Turn.user_id == user.id))
    assert turn is not None
    assert turn.modality == "voice"
    assert turn.words_per_minute == 120.0
    assert turn.mid_clause_pauses == 1
    assert turn.estimated_level == "B1"

    # The hallucinated finding must not have been stored.
    errors = list(await db.scalars(select(ErrorRecord).where(ErrorRecord.user_id == user.id)))
    assert len(errors) == 1
    assert errors[0].category == "tense_aspect"

    # Words met in conversation become cards.
    cards = await db.scalar(
        select(func.count()).select_from(UserCard).where(UserCard.user_id == user.id)
    )
    assert cards == 2

    # Usage is recorded from day one, so the cost of a user is observable.
    usage = await db.scalar(select(UsageDay).where(UsageDay.user_id == user.id))
    assert usage is not None
    assert usage.voice_turns == 1
    assert usage.llm_input_tokens == 300  # 100 + 200

    assert convo.turn_count == 1
    assert convo.voice_turn_count == 1


@pytest.mark.asyncio
async def test_memory_and_weak_spots_reach_the_prompt(db, fixtures, monkeypatch):
    """The differentiator: the tutor is told what it already knows."""
    user, topic, convo = fixtures
    user.memory_summary = "Works as an architect in Moscow, loves cycling."
    stub = StubBackend()
    monkeypatch.setattr(llm, "get_backend", lambda: stub)

    await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic, text="I go to shop yesterday",
        modality="text",
    )
    # Second turn now has the first turn's error category in recent history.
    await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic, text="I go to shop yesterday",
        modality="text",
    )

    assert "architect in Moscow" in stub.last_system
    assert "tense_aspect" in stub.last_system
    assert topic.goal_prompt in stub.last_system


@pytest.mark.asyncio
async def test_history_starts_with_a_user_message(db, fixtures):
    """Every provider rejects a conversation that opens on the assistant."""
    user, topic, convo = fixtures
    history = convo_service._build_history(convo, [], "hello")
    assert history[0]["role"] == "user"
    assert history[1]["content"] == convo.opening_line
    assert history[-1] == {"role": "user", "content": "hello"}
    roles = [m["role"] for m in history]
    assert all(a != b for a, b in zip(roles, roles[1:])), "roles must alternate"


@pytest.mark.asyncio
async def test_level_moves_slowly_not_in_one_jump(db, fixtures, monkeypatch):
    """One utterance is noisy; a single good sentence must not promote anyone."""
    user, topic, convo = fixtures
    user.level_score = 50.0
    user.productive_level = "B1"
    monkeypatch.setattr(llm, "get_backend", lambda: StubBackend())

    before = user.level_score
    await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic, text="I go to shop yesterday",
        modality="text",
    )
    assert abs(user.level_score - before) < 3
    assert user.productive_level == "B1"
    # Receptive runs a band ahead of productive.
    assert user.receptive_level == "B2"


class VisionStub(StubBackend):
    """A backend that can also look at images."""

    def __init__(self, description="A desk by a window with a laptop and a cup of tea."):
        super().__init__()
        self.description = description
        self.image_calls = 0

    async def describe_image(self, *, image, mime, prompt, max_tokens):
        self.image_calls += 1
        return self.description, Usage(50, 30)


@pytest.mark.asyncio
async def test_a_photo_turn_is_stored_but_never_assessed(db, fixtures, monkeypatch):
    """The description is the model's words, not the learner's. Grading it
    would invent errors they never made and file them in their history."""
    user, topic, convo = fixtures
    stub = VisionStub()
    monkeypatch.setattr(llm, "get_backend", lambda: stub)

    result = await convo_service.process_turn(
        db,
        user=user,
        convo=convo,
        topic=topic,
        text="",
        modality="photo",
        photo_description=stub.description,
        image_file_id="AgACAgIAAx0Cfake",
    )

    assert result.reply
    assert stub.json_calls == 0, "the assessor must not run on a photo turn"
    assert result.assessment is None

    turn = await db.scalar(select(Turn).where(Turn.modality == "photo"))
    assert turn is not None
    assert turn.image_file_id == "AgACAgIAAx0Cfake"
    assert stub.description in turn.user_text
    assert turn.error_count == 0

    errors = await db.scalar(
        select(func.count()).select_from(ErrorRecord).where(ErrorRecord.user_id == user.id)
    )
    assert errors == 0


@pytest.mark.asyncio
async def test_the_photo_stays_in_context_for_later_turns(db, fixtures, monkeypatch):
    """The point of the feature: the tutor can still refer to the picture
    several turns later, the way a person would."""
    user, topic, convo = fixtures
    stub = VisionStub()
    monkeypatch.setattr(llm, "get_backend", lambda: stub)

    await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic, text="",
        modality="photo", photo_description=stub.description,
    )
    await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic,
        text="It is my favourite place", modality="text",
    )

    history = await SessionRepo(db).history(convo.id, limit=10)
    combined = " ".join(t.user_text for t in history)
    assert "laptop and a cup of tea" in combined


@pytest.mark.asyncio
async def test_a_photo_turn_does_not_count_as_a_voice_turn(db, fixtures, monkeypatch):
    """Free-tier quotas are metered on speech; a picture is not speech."""
    user, topic, convo = fixtures
    stub = VisionStub()
    monkeypatch.setattr(llm, "get_backend", lambda: stub)

    await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic, text="",
        modality="photo", photo_description=stub.description,
    )

    usage = await db.scalar(select(UsageDay).where(UsageDay.user_id == user.id))
    assert usage.voice_turns == 0
    assert convo.voice_turn_count == 0
    assert convo.turn_count == 1
