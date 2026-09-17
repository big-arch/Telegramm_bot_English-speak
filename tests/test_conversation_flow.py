"""End-to-end test of one conversational turn against a real SQLite database.

The model is stubbed; everything else is the production path — the same
repositories, the same upserts, the same schema. This is the test that would
have caught a Postgres-only construct sneaking into the free SQLite stack.
"""

from __future__ import annotations

import httpx
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


def test_show_marker_is_removed_before_anything_speaks_it():
    """A synthesiser reading "bracket show colon brooklyn bridge" out loud is
    worse than no picture at all."""
    from bot.services.images import extract_request

    text, query = extract_request(
        "That bridge is beautiful at sunset. [SHOW: brooklyn bridge] Have you been?"
    )
    assert query == "brooklyn bridge"
    assert "SHOW" not in text and "[" not in text
    assert text == "That bridge is beautiful at sunset. Have you been?"


def test_a_reply_without_a_marker_is_untouched():
    from bot.services.images import extract_request

    original = "What did you do at the weekend?"
    text, query = extract_request(original)
    assert text == original and query is None


def test_marker_matching_is_forgiving_about_spacing_and_case():
    from bot.services.images import extract_request

    for raw in ("[SHOW: tokyo]", "[show:tokyo]", "[ Show : tokyo ]"):
        _text, query = extract_request(f"Look. {raw}")
        assert query == "tokyo", raw


def test_diagrams_and_logos_are_not_offered_as_photographs():
    """Commons is full of maps and coats of arms. Describing a diagram is a
    different exercise from describing a scene."""
    from bot.services.images import _is_photo

    assert _is_photo("File:Brooklyn Bridge at dusk.jpg")
    assert not _is_photo("File:Map of New York City.png")
    assert not _is_photo("File:Coat of arms of Paris.svg")
    assert not _is_photo("File:Nike logo.png")


@pytest.mark.asyncio
async def test_a_reply_asking_for_a_photo_stores_the_clean_text(db, fixtures, monkeypatch):
    """What goes in the history is what was said, not the instruction."""
    user, topic, convo = fixtures

    class ShowingStub(StubBackend):
        async def complete(self, *, system, messages, max_tokens):
            self.reply_calls += 1
            self.last_system = system
            return "Here it is. [SHOW: brooklyn bridge] What do you notice?", Usage(10, 5)

    monkeypatch.setattr(llm, "get_backend", lambda: ShowingStub())

    result = await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic, text="show me new york", modality="text",
    )

    assert result.photo_query == "brooklyn bridge"
    assert "SHOW" not in result.reply
    turn = await db.scalar(select(Turn).where(Turn.user_id == user.id))
    assert "SHOW" not in turn.assistant_text


def test_an_outright_request_for_a_photo_is_detected_in_code():
    """The feature cannot depend on a smaller model obeying an instruction
    buried in a long system prompt — "show me New York" answered with "I can't
    send photos" is the exact failure it exists to prevent."""
    from bot.services.images import detect_request

    cases = {
        "Show me New York": "New York",
        "show me a photo of the Eiffel Tower": "Eiffel Tower",
        "Can you send me a picture of Big Ben?": "Big Ben",
        "What does a London bus look like?": "London bus",
        "can I see the Golden Gate Bridge": "Golden Gate Bridge",
        "покажи мне Нью-Йорк": "Нью-Йорк",
    }
    for utterance, expected in cases.items():
        assert detect_request(utterance) == expected, utterance


def test_a_request_is_cut_down_to_a_searchable_subject():
    """From a real session. The capture has to be greedy to survive speech-to-
    text's missing punctuation, so everything after the subject is trimmed —
    Commons answers "just ties. Can you do it" with nothing at all."""
    from bot.services.images import detect_request

    cases = {
        "you can send me just ties. Can you do it?": "ties",
        "Show me the Colosseum and tell me about it": "Colosseum",
        "please send me a picture of a red panda now": "red panda",
        "Can you show me Tokyo? I've never been.": "Tokyo",
    }
    for utterance, expected in cases.items():
        assert detect_request(utterance) == expected, utterance


def test_a_promised_photo_is_looked_up_even_without_the_marker():
    """The failure from the screenshot: the tutor wrote "Sure, here's a picture
    of a pair of shiny black tights" and sent nothing. Once the promise is made
    to the learner, the promise decides — not whether the model remembered its
    instructions."""
    from bot.services.images import detect_promise

    cases = {
        "Sure, here's a picture of a pair of shiny black tights. How does it look?":
            "pair of shiny black tights",
        "Here is a photo of the Brooklyn Bridge!": "Brooklyn Bridge",
        "Let me show you my favourite building in Chicago": "my favourite building in Chicago",
        "This is a picture of a typical London pub.": "typical London pub",
    }
    for reply, expected in cases.items():
        assert detect_promise(reply) == expected, reply

    # An ordinary reply must not summon a picture out of nowhere.
    for reply in ("I love that photo you sent.", "What does it look like?", ""):
        assert detect_promise(reply) is None, reply


def test_the_tutor_will_not_go_looking_for_photos_of_itself_or_for_porn():
    """Commons is a public archive, not a curated classroom library, and the
    moment the tutor can deliver what it is asked for, the request becomes a
    steering wheel. Ordinary subjects must stay untouched."""
    from bot.services.images import allowed

    for query in (
        "your legs",
        "your face",
        "yourself in tights",
        "a photo of you",
        "send me a selfie",
        "naked woman",
        "lingerie model",
    ):
        assert not allowed(query), query

    for query in (
        "black tights",
        "your city",          # the persona's home town is a fine thing to show
        "your favourite building",
        "New York",
        "a flamingo's legs",  # anatomy in a vocabulary lesson is not the problem
        "the human body",
    ):
        assert allowed(query), query


def test_ordinary_conversation_does_not_trigger_a_photo():
    """A spurious picture is more jarring than a missing one."""
    from bot.services.images import detect_request

    for utterance in (
        "I went to New York last year",
        "New York is my favourite city",
        "It looks like rain today",
        "I want to show my friend the photos",  # not addressed to the tutor
        "",
        "show",
    ):
        assert detect_request(utterance) is None, utterance


@pytest.mark.asyncio
async def test_asking_to_be_shown_something_yields_a_photo_even_without_a_marker(
    db, fixtures, monkeypatch
):
    user, topic, convo = fixtures

    class SilentStub(StubBackend):
        async def complete(self, *, system, messages, max_tokens):
            self.reply_calls += 1
            self.last_system = system
            # The failure mode observed in production.
            return "I'm sorry, but I can't send photos.", Usage(10, 5)

    monkeypatch.setattr(llm, "get_backend", lambda: SilentStub())

    result = await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic,
        text="Send me a photo of New York", modality="voice",
    )
    assert result.photo_query == "New York"


@pytest.mark.asyncio
async def test_a_tutor_who_announces_a_photo_actually_sends_one(db, fixtures, monkeypatch):
    """The reported bug, end to end: the reply promised a picture, the marker
    was missing, and nothing arrived."""
    user, topic, convo = fixtures

    class PromisingStub(StubBackend):
        async def complete(self, *, system, messages, max_tokens):
            self.reply_calls += 1
            self.last_system = system
            return (
                "Sure, here's a picture of a pair of shiny black tights. "
                "How do they look in the light?",
                Usage(10, 5),
            )

    monkeypatch.setattr(llm, "get_backend", lambda: PromisingStub())

    result = await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic,
        text="Okay, can you send me just tights?", modality="voice",
    )
    assert result.photo_query == "pair of shiny black tights"


@pytest.mark.asyncio
async def test_a_refused_subject_stays_silent_rather_than_apologetic(
    db, fixtures, monkeypatch
):
    """The tutor's own words have already declined; following them with "I
    couldn't find that photo" would reframe a boundary as a failed search."""
    user, topic, convo = fixtures

    class DecliningStub(StubBackend):
        async def complete(self, *, system, messages, max_tokens):
            self.reply_calls += 1
            self.last_system = system
            return "I can't share personal photos — but tell me about them.", Usage(10, 5)

    monkeypatch.setattr(llm, "get_backend", lambda: DecliningStub())

    result = await convo_service.process_turn(
        db, user=user, convo=convo, topic=topic,
        text="Can you send me your legs and tights?", modality="voice",
    )
    assert result.photo_query is None


# --------------------------------------------------------------------------- #
# Finding the picture
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, payload=None, *, content_type="application/json", content=b"x" * 2048):
        self._payload = payload
        self.headers = {"content-type": content_type}
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _wiki_payload(title="Hamburger", source="https://upload.wikimedia.org/a/ham.jpg"):
    return {"query": {"pages": {"1": {"index": 1, "title": title,
                                      "thumbnail": {"source": source}}}}}


@pytest.mark.asyncio
async def test_a_failing_archive_does_not_take_the_feature_with_it(monkeypatch):
    """The production failure: one source went quiet and photos stopped
    entirely. Wikipedia is preferred, but preference is not dependence."""
    from bot.services import images

    async def get(self, url, **kwargs):
        if url == images.WIKIPEDIA_API:
            raise httpx.ConnectError("boom")
        if url == images.COMMONS_API:
            return _FakeResponse({"query": {"pages": {"1": {
                "index": 1, "title": "File:Burger.jpg",
                "imageinfo": [{"thumburl": "https://upload.wikimedia.org/b/burger.jpg"}],
            }}}})
        return _FakeResponse({"results": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    url, notes = await images.look_up("hamburger")
    assert url == "https://upload.wikimedia.org/b/burger.jpg"
    # And the failure is reported rather than swallowed — this module runs
    # where nobody in the conversation can read the logs.
    assert any("wikipedia" in note and "ConnectError" in note for note in notes)


@pytest.mark.asyncio
async def test_the_earliest_source_that_answered_wins(monkeypatch):
    """Racing must not cost quality: whoever replies first, the encyclopaedia's
    curated lead image still beats an archive keyword match."""
    from bot.services import images

    async def get(self, url, **kwargs):
        if url == images.WIKIPEDIA_API:
            return _FakeResponse(_wiki_payload())
        if url == images.COMMONS_API:
            return _FakeResponse({"query": {"pages": {"1": {
                "index": 1, "title": "File:Other.jpg",
                "imageinfo": [{"thumburl": "https://upload.wikimedia.org/c/other.jpg"}],
            }}}})
        return _FakeResponse({"results": [{"url": "https://example.com/ov.jpg"}]})

    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    url, _ = await images.look_up("hamburger")
    assert url == "https://upload.wikimedia.org/a/ham.jpg"


@pytest.mark.asyncio
async def test_a_picture_is_drawn_only_after_every_archive_came_up_empty(monkeypatch):
    """A real photograph is worth more in a lesson than a generated one, so
    generation is the last resort — never the shortcut."""
    from bot.services import images

    calls = []

    async def get(self, url, **kwargs):
        calls.append(url)
        if url.startswith("https://image.pollinations.ai/"):
            return _FakeResponse(content_type="image/jpeg")
        if url == images.OPENVERSE_API:
            return _FakeResponse({"results": []})
        return _FakeResponse({"query": {"pages": {}}})

    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    url, notes = await images.look_up("a cat wearing a chef's hat")
    assert url is not None and url.startswith("https://image.pollinations.ai/")
    assert any("generated" in note for note in notes)
    # Every archive was asked first, on the full phrase and on the short one.
    assert calls.index(images.WIKIPEDIA_API) < calls.index(url)


@pytest.mark.asyncio
async def test_a_refused_subject_never_reaches_an_archive_or_a_generator(monkeypatch):
    """The filter has to sit under the generator too — generation will happily
    draw whatever it is asked for."""
    from bot.services import images

    async def get(self, url, **kwargs):  # pragma: no cover - must never run
        raise AssertionError(f"refused query still reached {url}")

    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    url, notes = await images.look_up("your legs in lingerie")
    assert url is None
    assert notes and "refused" in notes[0]


@pytest.mark.asyncio
async def test_a_non_image_response_is_not_offered_to_telegram(monkeypatch):
    """Telegram fetches these URLs itself and rejects anything that is not an
    image, so an HTML error page must never be passed off as a photo."""
    from bot.services import images

    async def get(self, url, **kwargs):
        if url.startswith("https://image.pollinations.ai/"):
            return _FakeResponse(content_type="text/html")
        if url == images.OPENVERSE_API:
            return _FakeResponse({"results": [{"url": "https://example.com/page.html"}]})
        return _FakeResponse({"query": {"pages": {}}})

    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    url, _ = await images.look_up("something obscure")
    assert url is None


# --------------------------------------------------------------------------- #
# Looking at the learner's photo
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_dead_vision_model_does_not_blind_the_bot(monkeypatch):
    """The reported failure: conversation worked, photos did not. Vision was
    the one path pinned to a single vendor, so one retired model name took the
    whole feature out while everything else carried on."""
    from bot.services import vision
    from bot.services.backends.base import VisionUnsupported

    class Blind:
        async def describe_image(self, **kwargs):
            raise VisionUnsupported("404 model not found")

    class Seeing:
        async def describe_image(self, **kwargs):
            return "A cat asleep on a windowsill.", Usage(20, 30)

    monkeypatch.setattr(vision, "_candidates", lambda: ["gemini", "groq"])
    monkeypatch.setattr(vision, "_backend", lambda p: Blind() if p == "gemini" else Seeing())

    text, usage, notes = await vision.describe(b"x" * 64)
    assert text == "A cat asleep on a windowsill."
    assert usage.output_tokens == 30
    # The dead provider is named rather than silently skipped.
    assert any("gemini" in note and "404" in note for note in notes)


@pytest.mark.asyncio
async def test_when_nothing_can_see_the_reasons_survive(monkeypatch):
    """"Couldn't see it" is a symptom. The learner is the only person who can
    carry the cause back to someone who can fix it."""
    from bot.services import vision

    class Broken:
        def __init__(self, why):
            self.why = why

        async def describe_image(self, **kwargs):
            raise RuntimeError(self.why)

    monkeypatch.setattr(vision, "_candidates", lambda: ["gemini", "groq"])
    monkeypatch.setattr(
        vision, "_backend", lambda p: Broken("quota exhausted" if p == "gemini" else "bad key")
    )

    text, _, notes = await vision.describe(b"x" * 64)
    assert text is None
    assert any("quota exhausted" in note for note in notes)
    assert any("bad key" in note for note in notes)


def test_every_keyed_provider_is_a_vision_candidate(monkeypatch):
    """Preference leads, but it must not be the only one tried."""
    from bot.config import settings as cfg
    from bot.services import vision
    from pydantic import SecretStr

    monkeypatch.setattr(cfg, "vision_provider", "gemini")
    monkeypatch.setattr(cfg, "gemini_api_key", SecretStr("g"))
    monkeypatch.setattr(cfg, "groq_api_key", SecretStr("q"))
    monkeypatch.setattr(cfg, "anthropic_api_key", None)

    assert vision._candidates() == ["gemini", "groq"]

    monkeypatch.setattr(cfg, "vision_provider", "off")
    assert vision._candidates() == []
    assert vision.available() is False


def test_a_retired_gemini_model_is_recognised_from_its_error():
    """Google reports it as a 404 whose text names no model, so both the code
    and the wording have to be enough to act on."""
    from google.genai import errors as genai_errors

    from bot.services.backends.gemini_backend import _is_missing

    class Fake(genai_errors.APIError):
        def __init__(self, code, message):
            self.code = code
            self.message = message

        def __str__(self):
            return self.message

    assert _is_missing(Fake(404, "models/gemini-3.6-flash is not found"))
    assert _is_missing(Fake(400, "model is not available to new users"))
    assert not _is_missing(Fake(429, "resource exhausted"))
