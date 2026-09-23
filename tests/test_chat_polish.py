"""The chat's own presentation: the debrief card and its markup.

Telegram rejects an HTML message with one unbalanced tag or one bare "&", and
the whole message is lost, not just the bad part. Everything shown here mixes
the learner's words and the model's with markup, so the markup is checked by
parsing it, not by eye.
"""

from __future__ import annotations

from html.parser import HTMLParser
from types import SimpleNamespace

from bot.handlers.conversation import _debrief_text, _plural
from bot.services.llm import Finding

ALLOWED = {"b", "i", "s", "u", "code", "pre", "a", "blockquote", "tg-spoiler"}


class _Balance(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.bad = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED:
            self.bad.append(tag)
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.bad.append(f"/{tag}")


def assert_telegram_html(text: str) -> None:
    parser = _Balance()
    parser.feed(text)
    parser.close()
    assert not parser.bad and not parser.stack, (parser.bad, parser.stack)
    # A bare ampersand is the classic way to lose a whole message.
    import re
    stripped = re.sub(r"&(amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);", "", text)
    assert "&" not in stripped


def _finding(**kw):
    base = dict(original_span="I go to shop", correction="I went to the shop",
                category="tense_aspect", severity="noticeable",
                explanation="Past events take the past simple.")
    base.update(kw)
    return Finding(**base)


def test_the_debrief_is_valid_telegram_html_even_with_hostile_text():
    text = _debrief_text(
        SimpleNamespace(scenario_key="coffee", goals_done="0,1,2"),
        turns=7, wpm=112.0, accuracy=74.0, progress_line="Pauses < 1s & shorter",
        findings=[_finding(original_span="rock & roll", correction="<rock> and roll",
                           explanation="Use 'and' — \"&\" is for logos.")],
    )
    assert_telegram_html(text)
    assert "rock &amp; roll" in text


def test_a_finished_scene_leads_the_debrief():
    text = _debrief_text(
        SimpleNamespace(scenario_key="coffee", goals_done="0,1,2"),
        turns=5, wpm=None, accuracy=None, progress_line=None, findings=[],
    )
    lines = text.splitlines()
    assert "Кофейня" in lines[1] and "пройден" in lines[1]


def test_an_unfinished_scene_says_how_far_it_got():
    text = _debrief_text(
        SimpleNamespace(scenario_key="coffee", goals_done="0"),
        turns=3, wpm=None, accuracy=None, progress_line=None, findings=[],
    )
    assert "1 из 3" in text


def test_a_clean_session_has_no_empty_section_and_no_double_gaps():
    text = _debrief_text(
        SimpleNamespace(scenario_key=None, goals_done=None),
        turns=1, wpm=None, accuracy=None, progress_line=None, findings=[],
    )
    assert "Над чем поработать" not in text
    assert "\n\n\n" not in text
    assert_telegram_html(text)


def test_russian_plurals():
    assert [_plural(n, "реплика", "реплики", "реплик") for n in (1, 2, 5, 11, 21, 22, 112)] == [
        "реплика", "реплики", "реплик", "реплик", "реплика", "реплики", "реплик",
    ]


def test_the_scenario_card_and_finish_are_valid_html():
    from bot import scenarios

    for scenario in scenarios.SCENARIOS:
        assert_telegram_html(scenarios.card(scenario, {0}))
        assert_telegram_html(scenarios.card(scenario, {0, 1, 2}, finished=True))
