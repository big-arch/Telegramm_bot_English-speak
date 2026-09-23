""""How could I answer?" — three graded replies for a learner who is stuck.

A blank pause on a voice call is exactly the moment anxiety wins, which is why
this button exists. What matters: it always produces something, it answers the
line it sits under, it shows the same three when pressed twice, and it only
ever reads the learner's own conversation.
"""

from __future__ import annotations

import pytest

from bot.services import hints, llm
from bot.services.backends import Usage


@pytest.fixture(autouse=True)
def _fresh_cache():
    hints._cache.clear()
    yield
    hints._cache.clear()


class Structured:
    calls = 0

    async def complete_json(self, *, system, prompt, schema, max_tokens):
        Structured.calls += 1
        assert "What did your boss say?" in prompt, "hints must answer the actual line"
        return schema(hints=[
            hints.Hint(en="1. Not much, honestly.", ru="Честно, немного."),
            hints.Hint(en="He said it was fine, but he looked annoyed.", ru="Сказал, что всё ок."),
            hints.Hint(en="He'd been expecting it, so he wasn't surprised.", ru="Он ждал этого."),
            hints.Hint(en="a fourth one nobody asked for", ru=""),
        ]), Usage()

    async def complete(self, **kwargs):  # pragma: no cover
        raise AssertionError("structured output worked; no fallback needed")


@pytest.mark.asyncio
async def test_three_graded_replies_to_the_line_itself(monkeypatch):
    monkeypatch.setattr(llm, "get_backend", lambda: Structured())
    got = await hints.suggest(7, "What did your boss say?", "B1")

    assert len(got) == 3, "three, not four"
    assert got[0].en == "Not much, honestly.", "numbering the model added is stripped"
    assert got[2].ru == "Он ждал этого."


@pytest.mark.asyncio
async def test_pressing_twice_shows_the_same_three(monkeypatch):
    """A hint that changes when you look again is harder to use, not easier."""
    Structured.calls = 0
    monkeypatch.setattr(llm, "get_backend", lambda: Structured())
    first = await hints.suggest(7, "What did your boss say?", "B1")
    second = await hints.suggest(7, "What did your boss say?", "B1")
    assert first == second and Structured.calls == 1


@pytest.mark.asyncio
async def test_plain_text_when_json_will_not_cooperate(monkeypatch):
    class NoJson:
        async def complete_json(self, **kwargs):
            return None, Usage()

        async def complete(self, *, system, messages, max_tokens):
            return "Yeah, I think so.\n2) Not really, why?\n\nMaybe later!", Usage()

    monkeypatch.setattr(llm, "get_backend", lambda: NoJson())
    got = await hints.suggest(8, "Want to grab a coffee?", "A2")
    assert [h.en for h in got] == ["Yeah, I think so.", "Not really, why?", "Maybe later!"]


@pytest.mark.asyncio
async def test_a_failure_is_an_empty_list_not_a_crash(monkeypatch):
    class Broken:
        async def complete_json(self, **kwargs):
            raise RuntimeError("quota")

        async def complete(self, **kwargs):
            raise RuntimeError("quota")

    monkeypatch.setattr(llm, "get_backend", lambda: Broken())
    assert await hints.suggest(9, "Hi!", "A1") == []


def test_russian_only_for_beginners():
    """Past A2, a translation beside every suggestion is a crutch that stops
    them reading the English."""
    got = [hints.Hint(en="Sounds good & fun", ru="Звучит отлично")]
    beginner = hints.render(got, with_russian=True)
    later = hints.render(got, with_russian=False)

    assert "Звучит отлично" in beginner and "Звучит отлично" not in later
    assert "&amp;" in beginner, "suggestions are escaped like everything else"
    # Offered as material, not a script.
    assert "своими словами" in beginner


def test_every_tutor_reply_carries_the_button_and_the_opening_line_does_too():
    from bot.callbacks import HintCB
    from bot.keyboards.common import opening_kb, reader_kb

    def callbacks(markup):
        return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]

    assert HintCB(turn_id=42).pack() in callbacks(reader_kb(42))
    # The first line of a conversation is where a beginner freezes most.
    assert HintCB(turn_id=0).pack() in callbacks(opening_kb())
