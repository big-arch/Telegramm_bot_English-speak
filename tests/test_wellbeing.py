"""Noticing how the learner is.

The false positives matter more than the true ones here. English is full of
idioms that read as catastrophic and mean nothing — "this exam is killing me",
"I'm dying to see it" — and interrupting a lesson to hand someone a crisis
message they did not need is alarming, patronising, and an excellent reason
never to open the app again. So most of this file is about what must NOT fire.
"""

from __future__ import annotations

import pytest

from bot.services import wellbeing


@pytest.mark.parametrize(
    "utterance",
    [
        "I want to kill myself",
        "sometimes I think about hurting myself",
        "I don't want to live anymore",
        "I've been feeling suicidal",
        "everyone would be better off without me",
        "my husband hits me and I am scared",
        "я не хочу больше жить",
        "хочу умереть",
        "думаю покончить с собой",
        "меня бьют дома",
    ],
)
def test_a_real_crisis_stops_the_lesson(utterance):
    assert wellbeing.read(utterance).crisis is True


@pytest.mark.parametrize(
    "utterance",
    [
        # Idiom, every one of them.
        "This exam is killing me",
        "I'm dying to see the new film",
        "I could kill for a coffee right now",
        "my boss is killing me with these deadlines",
        "that joke killed me haha",
        "я умираю с голоду",
        "я убил весь день на эту задачу",
        # Ordinary bad days. Real, worth answering — but not an emergency.
        "I had a terrible week at work",
        "I'm so tired of this project",
        "I feel sad today",
        "мне сегодня грустно",
        # And the everyday business of the app.
        "I went to the shop yesterday",
        "",
    ],
)
def test_ordinary_speech_is_never_mistaken_for_a_crisis(utterance):
    assert wellbeing.read(utterance).crisis is False


@pytest.mark.parametrize(
    "utterance",
    [
        "I'm feeling really lonely lately",
        "I am so stressed about the interview",
        "I lost my job last week",
        "I feel like a failure",
        "I'll never be good at this",
        "мне тяжело",
        "я выгорел",
        "ничего не получается",
    ],
)
def test_a_hard_week_is_noticed_without_being_an_emergency(utterance):
    reading = wellbeing.read(utterance)
    assert reading.crisis is False
    assert reading.needs_care is True
    assert "answer the person before you answer the english" in wellbeing.guidance(reading).lower()


@pytest.mark.parametrize(
    "utterance",
    [
        "sorry for my English",
        "my English is terrible",
        "I'm afraid to speak because I make mistakes",
        "извините за мой английский",
        "боюсь говорить",
    ],
)
def test_apologising_for_your_own_english_is_the_signal_that_matters(utterance):
    """The best-documented predictor of who stops, and it always arrives
    disguised as politeness."""
    reading = wellbeing.read(utterance)
    assert reading.language_anxiety is True

    advice = wellbeing.guidance(reading)
    assert "apologising for their own english" in advice.lower()
    # Empty praise reads as pity and is the obvious wrong move.
    assert "specific and true" in advice


def test_an_ordinary_turn_adds_nothing_to_the_prompt():
    """Silence is the default. Every extra instruction is another one the model
    can drop, and most turns are just someone talking about their weekend."""
    reading = wellbeing.read("I went to Prague with my brother in May")
    assert reading.needs_care is False
    assert wellbeing.guidance(reading) == ""


def test_a_crisis_short_circuits_everything_else():
    """Nothing else about that turn is worth computing, and the caller is not
    going to use it."""
    reading = wellbeing.read("I want to kill myself, sorry for my English")
    assert reading.crisis is True
    assert reading.distress is False and reading.language_anxiety is False


def test_the_crisis_message_admits_what_it_is_and_points_somewhere_real():
    """A language bot is not help. Saying so plainly is the only honest move,
    and the message must not invent a helpline number to look reassuring."""
    from bot.texts import CRISIS_HELP

    assert "программа" in CRISIS_HELP
    assert "112" in CRISIS_HELP
    assert "довер" in CRISIS_HELP or "близк" in CRISIS_HELP
    # Never promise counselling it cannot give.
    for word in ("терапи", "лечен", "диагно"):
        assert word not in CRISIS_HELP.lower()


def test_the_tutor_is_told_what_it_is_not():
    from bot.services.prompts import tutor_system

    system = tutor_system(
        persona_character="X", persona_accent="Y", level="B1",
        correction_style="balanced", memory=None, weak_categories=[], topic_goal=None,
    )
    assert "not a therapist" in system.lower()
    assert "never diagnose" in system.lower()
    assert "stop the lesson entirely" in system.lower()


def test_the_care_note_goes_last_so_the_prompt_prefix_still_caches():
    """Prompt caching is a prefix match. A per-turn note anywhere but the end
    would move the boundary on every single turn and the cache would never hit."""
    from bot.services.prompts import tutor_system

    note = "THIS TURN. They have just said something about how they are feeling."
    system = tutor_system(
        persona_character="X", persona_accent="Y", level="B1",
        correction_style="balanced", memory="knows Prague", weak_categories=["article"],
        topic_goal="talk about travel", care=note,
    )
    assert system.rstrip().endswith(note)
