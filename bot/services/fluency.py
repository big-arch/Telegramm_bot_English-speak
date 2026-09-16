"""Fluency metrics from Whisper word timestamps.

Grading only the transcript throws away the most informative part of a spoken
answer. Complexity, Accuracy and Fluency trade off against each other — a
learner told to be accurate becomes slower and simpler — so measuring them
separately is what keeps normal development from looking like regression.

Everything here is computed from timestamps alone: no extra model call, no cost.
"""

from __future__ import annotations

from dataclasses import dataclass

# A silent gap at or above this counts as a pause. 0.25s and 0.4s are both used
# in the research; the numbers are not comparable across thresholds, so pick one
# and never change it, or your historical charts become meaningless.
PAUSE_THRESHOLD_SEC = 0.25

_SENTENCE_ENDINGS = (".", "?", "!", "…")


@dataclass
class FluencyMetrics:
    audio_seconds: float
    word_count: int
    words_per_minute: float
    articulation_wpm: float
    pause_ratio: float
    pause_count: int
    mid_clause_pauses: int
    mean_run_words: float

    def as_columns(self) -> dict[str, float | int]:
        return {
            "audio_seconds": self.audio_seconds,
            "word_count": self.word_count,
            "words_per_minute": self.words_per_minute,
            "articulation_wpm": self.articulation_wpm,
            "pause_ratio": self.pause_ratio,
            "mid_clause_pauses": self.mid_clause_pauses,
            "mean_run_words": self.mean_run_words,
        }


def compute(words: list[dict], duration: float) -> FluencyMetrics | None:
    """`words` is Whisper's word list: [{"word": str, "start": float, "end": float}].

    Returns None when there is too little signal to say anything honest — one or
    two words cannot support a fluency claim, and showing a number anyway is how
    a progress chart becomes noise.
    """
    usable = [w for w in words if w.get("start") is not None and w.get("end") is not None]
    if len(usable) < 5 or duration <= 0:
        return None

    word_count = len(usable)
    phonation = sum(max(0.0, w["end"] - w["start"]) for w in usable)
    phonation = max(phonation, 0.01)

    pause_total = 0.0
    pause_count = 0
    mid_clause = 0
    run_lengths: list[int] = []
    current_run = 1

    for prev, nxt in zip(usable, usable[1:]):
        gap = nxt["start"] - prev["end"]
        if gap >= PAUSE_THRESHOLD_SEC:
            pause_total += gap
            pause_count += 1
            run_lengths.append(current_run)
            current_run = 1
            # Fluent speakers pause at clause boundaries while planning the next
            # chunk; learners pause inside clauses while hunting for a word. Two
            # speakers with the same pause ratio can be at very different levels,
            # so the split matters more than the raw count. Whisper punctuation
            # is the best clause signal available without a parser.
            if not prev.get("word", "").strip().endswith(_SENTENCE_ENDINGS):
                mid_clause += 1
        else:
            current_run += 1
    run_lengths.append(current_run)

    return FluencyMetrics(
        audio_seconds=round(duration, 2),
        word_count=word_count,
        words_per_minute=round(word_count / duration * 60, 1),
        articulation_wpm=round(word_count / phonation * 60, 1),
        pause_ratio=round(min(pause_total / duration, 1.0), 3),
        pause_count=pause_count,
        mid_clause_pauses=mid_clause,
        mean_run_words=round(sum(run_lengths) / len(run_lengths), 1),
    )


# Rough conversational reference points, for turning a number into a sentence.
# These are broad bands from the literature, not a certified scale — use them to
# say "faster than last week", never "you are B2 because you hit 145 wpm".
_WPM_BANDS = ((90, "A1"), (115, "A2"), (140, "B1"), (165, "B2"))


def pace_band(wpm: float) -> str:
    for threshold, band in _WPM_BANDS:
        if wpm < threshold:
            return band
    return "C1"


def describe_progress(current: FluencyMetrics, previous: FluencyMetrics | None) -> str | None:
    """One sentence of honest, self-referential progress. None if nothing to say.

    Comparing a learner to a native baseline shows them a permanent gap.
    Comparing them to their own last session shows them movement, which is the
    thing that brings people back.
    """
    if previous is None:
        return None

    wpm_delta = current.words_per_minute - previous.words_per_minute
    pause_delta = previous.pause_ratio - current.pause_ratio
    run_delta = current.mean_run_words - previous.mean_run_words

    if wpm_delta >= 8:
        return f"Ты говорил быстрее, чем в прошлый раз — {current.words_per_minute:.0f} слов в минуту."
    if pause_delta >= 0.04:
        return "Пауз посреди фраз стало меньше — речь звучит слитнее."
    if run_delta >= 1.5:
        return f"Ты стал говорить более длинными кусками без остановок — в среднем {current.mean_run_words:.0f} слов подряд."
    return None
