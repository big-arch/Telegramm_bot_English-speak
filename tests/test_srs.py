from bot.services import srs


def test_first_successful_reviews_follow_sm2_schedule():
    state = srs.CardState()
    state = srs.review(state, 3)
    assert state.interval_days == 1
    state = srs.review(state, 3)
    assert state.interval_days == 6
    state = srs.review(state, 3)
    assert state.interval_days > 6


def test_easy_grows_ease_and_hard_shrinks_it():
    easy = srs.review(srs.CardState(), 4)
    hard = srs.review(srs.CardState(), 2)
    assert easy.ease > 2.5 > hard.ease


def test_ease_never_falls_below_floor():
    state = srs.CardState()
    for _ in range(50):
        state = srs.review(state, 2)
    assert state.ease >= srs.EASE_FLOOR


def test_lapse_keeps_part_of_a_long_interval():
    """A card reviewed for a year should not reset to one day after one bad morning."""
    mature = srs.CardState(interval_days=200, ease=2.5, reps=8)
    lapsed = srs.review(mature, 1)
    assert lapsed.lapses == 1
    assert lapsed.reps == 0
    assert 1 < lapsed.interval_days < 200


def test_lapse_on_a_new_card_still_gives_at_least_a_day():
    lapsed = srs.review(srs.CardState(), 1)
    assert lapsed.interval_days >= 1


def test_relative_overdueness_ranks_the_at_risk_card_first():
    """After a long absence, the oldest card is not the most urgent one."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    # Stable card: 200-day interval, 10 days late — barely at risk.
    stable = srs.relative_overdueness(now - timedelta(days=10), 200, now)
    # Fragile card: 2-day interval, 10 days late — long forgotten.
    fragile = srs.relative_overdueness(now - timedelta(days=10), 2, now)
    assert fragile > stable
