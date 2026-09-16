# Spaced repetition: SM-2 and FSRS

## The idea

Memory decays predictably. Reviewing an item just before it would be forgotten produces a much larger gain than reviewing it while it is still fresh, and each successful retrieval flattens the decay curve further. A scheduler's job is to predict the moment of near-forgetting and ask then.

Two knobs define the system: **desired retention** (what fraction of reviews should be correct — 0.85–0.90 is the usual sweet spot) and **the memory model** that turns review history into an interval.

## SM-2

The Anki-classic. No training data, trivially auditable, good enough to ship.

State per card: `interval` (days), `ease` (factor, starts 2.5, floor 1.3), `reps`.

Grade `q` on 0–5, where <3 is a failure. If your UI uses four buttons (Again/Hard/Good/Easy), map them to 0/3/4/5.

```python
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class SM2State:
    interval: int = 0      # days
    ease: float = 2.5
    reps: int = 0


def sm2(state: SM2State, q: int) -> SM2State:
    """q: 0..5. <3 counts as a lapse and restarts the interval."""
    if q < 3:
        return SM2State(interval=1, ease=state.ease, reps=0)

    ease = state.ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ease = max(1.3, ease)

    reps = state.reps + 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 6
    else:
        interval = round(state.interval * ease)

    return SM2State(interval=interval, ease=ease, reps=reps)


def next_due(state: SM2State) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=state.interval)
```

Known weaknesses, worth knowing before you attribute them to a bug:

- A lapse resets the interval to 1 day regardless of how well-established the card was. A card reviewed successfully for a year drops to square one after one bad day. Mitigate with a partial reset (`interval = max(1, round(old_interval * 0.3))`).
- `ease` drifts downward and never recovers well — the "ease hell" complaint. Floor it and consider capping the penalty.
- It ignores how long the actual gap was, only the scheduled one.

## FSRS

Models three quantities per card:

- **S (stability)** — days until retrievability falls to 90%.
- **D (difficulty)** — 1–10, how hard this item is for this learner.
- **R (retrievability)** — current probability of recall, a function of S and elapsed time.

The forgetting curve is a power function (which fits data better than the exponential SM-2 implicitly assumes):

```python
DECAY = -0.5
FACTOR = 19 / 81


def retrievability(elapsed_days: float, stability: float) -> float:
    return (1 + FACTOR * elapsed_days / stability) ** DECAY


def interval_for(stability: float, desired_retention: float = 0.9) -> float:
    """Days until retrievability drops to `desired_retention`."""
    return stability / FACTOR * (desired_retention ** (1 / DECAY) - 1)
```

Stability and difficulty are updated after each review by a set of fitted parameters (the count depends on the FSRS version — roughly 17 to 21). Do not hand-roll these formulas: use the maintained `fsrs` Python package, which ships sensible defaults and an optimiser.

```python
from fsrs import Scheduler, Card, Rating

scheduler = Scheduler()                     # default parameters
card, review_log = scheduler.review_card(card, Rating.Good)
# card.due, card.stability, card.difficulty are updated
```

The real win is **parameter optimisation**: fit the parameters to your own review logs (per cohort, or per user once they have enough history) and the schedule adapts to your material and your learners. That is why the log table matters.

## Which to use

Ship **SM-2**. It requires no data, no dependency, and the difference on a new product is invisible next to content quality and retention.

Move to **FSRS** when you have review logs at scale — roughly thousands of reviews across a cohort — and want to cut review load at equal retention (FSRS typically achieves the same retention with meaningfully fewer reviews). At that point the optimiser has something to chew on.

**Keep the schema compatible from day one** so the switch is not a migration crisis. Store, per review, an append-only row with: card id, timestamp, elapsed days since last review, grade, and the scheduler state *before* the review. That log is exactly what FSRS's optimiser needs, and without it you cannot backfit parameters — you would have to start collecting from zero.

## Queue management

The algorithm is only half the system. The other half is what the user sees.

- **Cap the daily queue** (e.g. 20 reviews + 5 new). An uncapped queue after a two-week absence shows 300 cards and the user leaves. Overflow gets rescheduled, not dropped.
- **New vs review ratio** — reviews first, always. Introducing new items while a backlog grows is how users end up with 400 due cards and no sense of progress.
- **Order within a session**: due-soonest first is fine, but *interleave item types*. Blocked practice (all vocabulary, then all grammar) feels easier and transfers worse.
- **Sibling burying** — do not show the recognition and production cards for the same word in one session; the first gives away the second.
- **Leeches** — an item lapsing repeatedly (say 8 times) is not a scheduling problem, it is a bad card. Suspend it and flag it for rewriting: usually the prompt is ambiguous or the item should be learned in a phrase rather than alone.

## Relative overdueness and long absences

When a user returns after weeks, every card is overdue by a different multiple. Sorting by `due_at` ascending shows the oldest first, which are often the most stable and least urgent. Sorting by **relative overdueness** (`elapsed / scheduled_interval`, descending) surfaces the cards genuinely at risk. FSRS gives this more directly: sort by current retrievability ascending.

## What to grade on

For vocabulary, a four-button grade (Again/Hard/Good/Easy) is the standard and works. But a bot has signals a flashcard app does not:

- **Response latency** — a slow correct answer is weaker than a fast one, and is a legitimate input to difficulty.
- **Production vs recognition** — producing the word in a sentence is stronger evidence than picking it from four options; weight accordingly.
- **Spoken use** — using the word correctly in free speech is the strongest evidence of all, and should be able to advance a card without an explicit review.

That last one is worth building: a bot that notices "you used *reluctant* correctly while talking" and credits the card is doing something a flashcard app structurally cannot.
