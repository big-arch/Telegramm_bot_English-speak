"""Numbers about the product, for whoever built it.

Two things are being asserted, and the second matters more than the first.
That the arithmetic is right — and that an analytics command does not answer
strangers, and never returns anything anyone said.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from bot.db.base import Base, engine, sessionmaker
from bot.db.models import Session, Turn, UsageDay, User, UserCard, Word
from bot.db.repositories import StatsRepo


@pytest_asyncio.fixture
async def populated():
    """Four people at four different depths, which is what a real bot looks
    like: most of them never say anything."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(timezone.utc)
    async with sessionmaker() as db:
        # 1. Arrived, pressed /start, never came back.
        lurker = User(tg_id=1, first_name="Lurker", created_at=now - timedelta(days=9),
                      last_seen_at=now - timedelta(days=9))
        # 2. Finished onboarding, said nothing.
        quiet = User(tg_id=2, first_name="Quiet", goal="travel",
                     created_at=now - timedelta(days=5), last_seen_at=now - timedelta(days=5))
        # 3. Spoke once, on one day only.
        oneshot = User(tg_id=3, first_name="Once", goal="work",
                       created_at=now - timedelta(days=3), last_seen_at=now - timedelta(days=3))
        # 4. Spoke on two different days — the only real user here.
        regular = User(tg_id=4, first_name="Regular", goal="work",
                       created_at=now - timedelta(hours=2), last_seen_at=now)
        db.add_all([lurker, quiet, oneshot, regular])
        await db.flush()

        for user, days in ((oneshot, [3]), (regular, [1, 0])):
            for offset in days:
                convo = Session(user_id=user.id, persona_key="emma")
                if user is regular and offset == 0:
                    convo.finished_at = now
                db.add(convo)
                await db.flush()
                db.add(Turn(
                    session_id=convo.id, user_id=user.id,
                    modality="voice" if user is regular else "text",
                    user_text="hi", assistant_text="hello",
                    created_at=now - timedelta(days=offset),
                ))

        word = Word(lemma="stubborn", pos="unknown", cefr="B1", translation_ru="упрямый")
        db.add(word)
        await db.flush()
        db.add(UserCard(user_id=regular.id, word_id=word.id, due_at=now, origin="tapped"))
        db.add(UsageDay(user_id=regular.id, day=now.strftime("%Y-%m-%d"),
                        reader_opens=3, review_opens=2, llm_input_tokens=100,
                        llm_output_tokens=50, audio_seconds_in=120.0))
        await db.commit()

        yield db

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_the_two_numbers_that_actually_matter(populated):
    """Total users only ever goes up and says nothing. How many of them spoke,
    and how many of those came back on a second day, says everything."""
    data = await StatsRepo(populated).overview()

    assert data["total"] == 4
    assert data["spoke"] == 2, "two of the four ever said anything"
    assert data["returned"] == 1, "and only one came back on another day"


@pytest.mark.asyncio
async def test_the_funnel_shows_where_people_stop(populated):
    """A step that loses most of the people who reached it is a bug with a
    location, which no single total can give you."""
    funnel = await StatsRepo(populated).funnel()
    counts = dict(funnel)

    assert counts["Нажали /start"] == 4
    assert counts["Выбрали уровень"] == 3
    assert counts["Сказали хоть что-то"] == 2
    assert counts["Записали голосовое"] == 1
    assert counts["Дошли до /finish"] == 1
    assert counts["Учат слова"] == 1

    # Monotonically narrowing, or it is not a funnel and the queries are wrong.
    values = [count for _, count in funnel]
    assert values == sorted(values, reverse=True)


@pytest.mark.asyncio
async def test_app_opens_are_counted_not_inferred(populated):
    """Inferring opens from taps cannot see the case worth seeing: someone who
    opened the app and did nothing at all."""
    data = await StatsRepo(populated).overview()
    assert data["reader_opens"] == 3
    assert data["review_opens"] == 2
    assert data["cards"] == 1 and data["tapped"] == 1


@pytest.mark.asyncio
async def test_activity_windows_and_cost_add_up(populated):
    data = await StatsRepo(populated).overview()

    assert data["active_today"] == 1
    # Everyone but the lurker, who was last seen nine days ago.
    assert data["active_week"] == 3
    assert data["active_month"] == 4
    assert data["new_today"] == 1
    assert data["voice"] == 2 and data["text"] == 1
    assert data["conversations"] == 3 and data["finished"] == 1
    assert data["llm_in"] == 100 and data["llm_out"] == 50
    assert data["audio_minutes"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_statistics_never_contain_anything_anybody_said(populated):
    """The operator needs to know whether the thing works, not what was said to
    it. A product that reads its users' conversations to measure itself has
    become a different product."""
    repo = StatsRepo(populated)
    everything = repr(await repo.overview()) + repr(await repo.funnel()) + repr(
        await repo.daily()
    )

    for private in ("hi", "hello", "Regular", "Lurker", "stubborn", "упрямый"):
        assert private not in everything, private


@pytest.mark.asyncio
async def test_an_empty_database_does_not_divide_by_zero(populated):
    """The state every bot is in on its first day, and the one most likely to
    be looked at."""
    from bot.handlers.stats import _bar, _percent

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker() as empty:
        data = await StatsRepo(empty).overview()
        assert data["total"] == 0 and data["returned"] == 0
        assert await StatsRepo(empty).daily() == []

    assert _percent(0, 0) == "—"
    assert _bar(0, 0) == ""


def test_stats_are_closed_by_default_and_never_confirm_themselves():
    """An analytics command that answers anyone is a way to find out how a
    stranger's product is doing — and a refusal message would confirm the
    command exists."""
    import inspect

    from bot.config import settings
    from bot.handlers import stats

    assert settings.admin_ids == [], "no admins unless the operator says so"

    source = inspect.getsource(stats.cmd_stats)
    # The non-admin branch returns without answering.
    assert "if tg_id not in settings.admin_ids:" in source
    non_admin = source.split("if tg_id not in settings.admin_ids:")[1].split("return")[0]
    assert "answer" not in non_admin
