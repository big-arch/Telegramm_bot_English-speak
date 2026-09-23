"""One door into speaking: scenes and free topics are tabs of the same picker."""

from __future__ import annotations

from types import SimpleNamespace

from bot import scenarios
from bot.callbacks import ScenarioCB, TalkCB, TopicCB
from bot.keyboards.common import main_kb, talk_kb


def _topic(i: int):
    return SimpleNamespace(id=i, emoji="☕", title_ru=f"Тема {i}")


def _callbacks(markup):
    return [[b.callback_data for b in row] for row in markup.inline_keyboard]


def test_tabs_sit_on_top_and_mark_the_open_one():
    for tab in ("scenes", "topics"):
        rows = talk_kb(tab, topics=[_topic(1)], level="B1").inline_keyboard
        tabs = rows[0]
        assert [TalkCB.unpack(b.callback_data).tab for b in tabs] == ["scenes", "topics"]
        marked = [b for b in tabs if b.text.startswith("·")]
        assert len(marked) == 1
        assert TalkCB.unpack(marked[0].callback_data).tab == tab


def test_scenes_tab_lists_every_scene_and_no_topics():
    body = sum(_callbacks(talk_kb("scenes", topics=[_topic(1)], level="B1"))[1:], [])
    keys = [ScenarioCB.unpack(c).key for c in body]
    assert sorted(keys) == sorted(s.key for s in scenarios.SCENARIOS)


def test_topics_tab_lists_topics_one_per_row():
    rows = _callbacks(talk_kb("topics", topics=[_topic(1), _topic(2)], level="B1"))[1:]
    assert [[TopicCB.unpack(c).topic_id for c in row] for row in rows] == [[1], [2]]


def test_panel_has_one_way_to_start_talking():
    labels = [b.text for b in main_kb().keyboard[0]]
    assert labels == ["💬 Говорить", "🔁 Слова", "🏁 Закончить", "☰ Ещё"]
