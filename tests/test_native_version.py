""""How a native speaker would say it" — shown only when it is worth asking for.

The rule of this product is that nobody is interrupted with corrections mid-
conversation. A spoiler is a correction you have to ask for, which is the only
kind allowed here, and even that is withheld when the learner has just said
something that deserves an answer rather than an edit.
"""

from __future__ import annotations

from types import SimpleNamespace

from bot.handlers.conversation import _heard
from bot.services.feedback import native_rewrite


def _result(rewritten: str | None):
    return SimpleNamespace(assessment=SimpleNamespace(rewritten=rewritten))


def test_a_real_improvement_is_offered():
    assert native_rewrite("I go to shop yesterday", "I went to the shop yesterday.") == (
        "I went to the shop yesterday."
    )


def test_transcription_noise_is_not_a_mistake():
    """Case, commas and full stops come from speech-to-text, not from the
    learner. A rewrite that only tidies them would teach someone they got
    something wrong that they got right."""
    assert native_rewrite("i went to the shop yesterday", "I went to the shop yesterday.") is None
    assert native_rewrite("well, it’s fine", "Well, it's fine.") is None
    assert native_rewrite("anything", "") is None
    assert native_rewrite("anything", None) is None


def test_it_is_hidden_until_asked_for():
    line = _heard("I go to shop yesterday", _result("I went to the shop yesterday."))
    assert "<tg-spoiler>I went to the shop yesterday.</tg-spoiler>" in line
    assert line.startswith("🗣 <i>I go to shop yesterday</i>")


def test_nothing_is_added_when_there_is_nothing_to_show():
    assert _heard("I went to the shop", _result("I went to the shop.")) == (
        "🗣 <i>I went to the shop</i>"
    )
    assert _heard("hello") == "🗣 <i>hello</i>"


def test_a_turn_that_carried_feeling_gets_no_grammar_note():
    """Nobody who has just said they lost their job should find an edit of
    their sentence underneath it."""
    line = _heard("I lost my job and I feel like a failure",
                  _result("I've lost my job, and I feel like a failure."))
    assert "tg-spoiler" not in line


def test_speech_that_looks_like_markup_cannot_break_the_message():
    """Whisper writes "rock & roll" like any other text. Unescaped, the
    ampersand made Telegram reject the edit and the whole turn failed."""
    line = _heard("I like rock & roll <3", _result("I like rock & roll <3!!"))
    assert "&amp;" in line and "&lt;3" in line
    assert "rock & roll" not in line
