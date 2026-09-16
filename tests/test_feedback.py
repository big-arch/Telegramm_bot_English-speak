from collections import Counter

from bot.services import feedback
from bot.services.llm import Finding


def finding(category, severity="noticeable", span="x", correction="y"):
    return Finding(
        original_span=span,
        correction=correction,
        category=category,
        severity=severity,
        explanation="because",
    )


def test_never_returns_more_than_three():
    """Eight simultaneous corrections is not feedback, it is a wall."""
    many = [
        finding(c)
        for c in (
            "article", "tense_aspect", "preposition", "word_order",
            "agreement", "word_choice", "modality",
        )
    ]
    assert len(feedback.select(many, level="B1")) <= feedback.MAX_CORRECTIONS


def test_blocking_errors_outrank_minor_ones():
    picked = feedback.select(
        [finding("word_choice", "minor"), finding("word_order", "blocking")],
        level="B1",
    )
    assert picked[0].severity == "blocking"


def test_structures_above_the_learners_level_are_deprioritised():
    """Flagging the conditional to an A1 learner teaches nothing."""
    picked = feedback.select(
        [finding("conditional", "noticeable"), finding("article", "noticeable")],
        level="A1",
        limit=1,
    )
    assert picked[0].category == "article"


def test_recurring_categories_win_over_one_off_slips():
    picked = feedback.select(
        [finding("preposition"), finding("word_form")],
        level="B2",
        recent_counts=Counter({"preposition": 5}),
        limit=1,
    )
    assert picked[0].category == "preposition"


def test_one_correction_per_category():
    picked = feedback.select([finding("article") for _ in range(5)], level="B1")
    assert len(picked) == 1


def test_clean_utterance_is_told_it_was_clean():
    rendered = feedback.render([])
    assert "Ошибок" in rendered


def test_hint_does_not_give_away_the_answer():
    """A prompt turns the correction into a retrieval; a reveal is just a fact."""
    f = finding("tense_aspect", span="I go yesterday", correction="I went yesterday")
    hint = feedback.hint_for(f)
    assert f.original_span in hint
    assert f.correction not in hint
