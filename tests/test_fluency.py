from bot.services import fluency


def words(spans):
    return [{"word": w, "start": s, "end": e} for w, s, e in spans]


FLUENT = words(
    [
        ("I", 0.0, 0.15),
        ("went", 0.15, 0.40),
        ("to", 0.40, 0.50),
        ("the", 0.50, 0.60),
        ("shop", 0.60, 0.90),
        ("yesterday.", 0.90, 1.40),
        ("It", 1.45, 1.60),
        ("was", 1.60, 1.80),
        ("closed.", 1.80, 2.20),
    ]
)


def test_returns_none_when_there_is_too_little_signal():
    """Two words cannot support a fluency claim; a number there would be noise."""
    assert fluency.compute(words([("hi", 0.0, 0.3)]), 0.3) is None
    assert fluency.compute(FLUENT, 0) is None


def test_basic_metrics():
    m = fluency.compute(FLUENT, 2.2)
    assert m is not None
    assert m.word_count == 9
    assert m.words_per_minute > 200  # fast, short sample
    assert 0.0 <= m.pause_ratio <= 1.0
    assert m.articulation_wpm >= m.words_per_minute


def test_hesitant_speech_scores_worse_than_fluent_speech():
    hesitant = words(
        [
            ("I", 0.0, 0.2),
            ("went", 1.2, 1.5),
            ("to", 2.4, 2.6),
            ("the", 3.5, 3.7),
            ("shop", 4.6, 5.0),
            ("yesterday.", 6.0, 6.5),
        ]
    )
    fast = fluency.compute(FLUENT, 2.2)
    slow = fluency.compute(hesitant, 6.5)
    assert fast is not None and slow is not None
    assert slow.words_per_minute < fast.words_per_minute
    assert slow.pause_ratio > fast.pause_ratio
    assert slow.mean_run_words < fast.mean_run_words


def test_mid_clause_pauses_exclude_sentence_boundaries():
    """Pausing after a full stop is normal; pausing inside a clause is the signal."""
    at_boundary = words([("one.", 0.0, 0.3), ("two", 1.5, 1.8), ("three", 1.8, 2.0),
                         ("four", 2.0, 2.2), ("five", 2.2, 2.4), ("six", 2.4, 2.6)])
    mid_clause = words([("one", 0.0, 0.3), ("two", 1.5, 1.8), ("three", 1.8, 2.0),
                        ("four", 2.0, 2.2), ("five", 2.2, 2.4), ("six", 2.4, 2.6)])
    a = fluency.compute(at_boundary, 2.6)
    b = fluency.compute(mid_clause, 2.6)
    assert a is not None and b is not None
    assert a.mid_clause_pauses == 0
    assert b.mid_clause_pauses == 1


def test_progress_is_measured_against_the_learner_not_a_native_baseline():
    previous = fluency.compute(FLUENT, 4.0)
    current = fluency.compute(FLUENT, 2.2)
    assert previous is not None and current is not None
    assert fluency.describe_progress(current, None) is None
    assert fluency.describe_progress(current, previous) is not None
