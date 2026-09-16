"""Spaced repetition (SM-2).

SM-2 rather than FSRS on purpose: it needs no training data, it is forty lines
you can audit, and on a new product the difference is invisible next to content
quality. `ReviewLog` records everything FSRS's optimiser would need, so the
switch later is a parameter fit rather than a restart from zero.

Grades are the four-button scale the UI shows: 1 Again, 2 Hard, 3 Good, 4 Easy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

EASE_FLOOR = 1.3
# A card reviewed successfully for a year should not drop to a 1-day interval
# because of one bad morning. Classic SM-2 resets to 1; this keeps 30% of the
# earned interval, which is the common fix for "ease hell".
LAPSE_RETENTION = 0.3


@dataclass
class CardState:
    interval_days: int = 0
    ease: float = 2.5
    reps: int = 0
    lapses: int = 0
    state: str = "new"


def review(card: CardState, grade: int) -> CardState:
    """Apply one review. Pure function — easy to test, easy to reason about."""
    if grade <= 1:
        return CardState(
            interval_days=max(1, round(card.interval_days * LAPSE_RETENTION)),
            ease=max(EASE_FLOOR, card.ease - 0.2),
            reps=0,
            lapses=card.lapses + 1,
            state="relearning",
        )

    # SM-2's ease update, with the 4-button scale mapped onto its 0-5 q.
    q = {2: 3, 3: 4, 4: 5}[grade]
    ease = card.ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ease = max(EASE_FLOOR, ease)

    reps = card.reps + 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 6
    else:
        interval = max(1, round(card.interval_days * ease))

    return CardState(
        interval_days=interval,
        ease=ease,
        reps=reps,
        lapses=card.lapses,
        state="review" if interval >= 21 else "learning",
    )


def due_at(state: CardState, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(days=state.interval_days)


def relative_overdueness(due: datetime, interval_days: int, now: datetime | None = None) -> float:
    """How at-risk a card is, relative to its own schedule.

    After a two-week absence everything is overdue. Sorting by due date surfaces
    the oldest cards, which are usually the most stable and least urgent;
    sorting by this surfaces the ones actually about to be forgotten.
    """
    now = now or datetime.now(timezone.utc)
    scheduled = max(interval_days, 1)
    elapsed_past_due = (now - due).total_seconds() / 86400
    return (elapsed_past_due + scheduled) / scheduled


# A backlog of 400 cards after a week away is how learning apps lose people.
DAILY_REVIEW_CAP = 20
DAILY_NEW_CAP = 6
