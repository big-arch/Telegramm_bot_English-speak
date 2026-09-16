# CEFR levelling and vocabulary selection

## Reading CEFR correctly

CEFR descriptors are *can-do* statements about communicative ability. The ones worth keeping close when tagging content:

| Level | Productive speaking, condensed |
|---|---|
| A1 | Simple phrases about immediate needs; interaction depends on the partner repeating and rephrasing. |
| A2 | Short social exchanges; describe family, background, immediate environment in simple terms. |
| B1 | Deal with most travel situations; connect phrases to describe experiences, plans, opinions with brief reasons. |
| B2 | Interact with fluency and spontaneity; sustained argument on a range of topics; regular interaction with native speakers without strain for either side. |
| C1 | Fluent and spontaneous without obvious searching; flexible and effective use for social, academic and professional purposes. |
| C2 | Effortless; precise shades of meaning; smooth reformulation around difficulty. |

Notice what is absent: grammar structures. A bot organised around "B1 = present perfect + first conditional" is teaching a syllabus, not a level. Tag content with the can-do it serves, and grammar follows as a means.

## Sub-levels and multi-dimensional level

Store, at minimum:

```
receptive_level   (listening/reading)
productive_level  (speaking/writing)
```

Receptive typically runs ~1 band ahead. A single `cefr_level` column forces you to either bore the user with easy input or hand them tasks they cannot produce.

Use a continuous internal score (e.g. 0–100 mapped onto A1–C2) updated after each session, and render it as a band. Continuous updating lets progress be visible between bands — moving from "A2, 20%" to "A2, 60%" is motivating; sitting at "A2" for three months is not.

## Frequency: the backbone of selection

Coverage figures that should drive decisions:

| Vocabulary size (word families) | Approx. text coverage |
|---|---|
| 1 000 | ~72–76% |
| 2 000 | ~80–85% |
| 3 000 | ~88% |
| 5 000 | ~93% |
| 8 000–9 000 | ~98% |

95% coverage is roughly the threshold for inferring unknown words from context; 98% for comfortable unassisted comprehension. The practical implication: **the first 2–3 thousand items are worth enormously more per item than anything after**, and a bot that lets a beginner spend time on low-frequency vocabulary is stealing from them.

Usable lists:

- **NGSL** (New General Service List, ~2 800 words) — modern, corpus-derived, high coverage of general English. Good default spine.
- **NAWL** (New Academic Word List, ~960) — for learners with academic goals, after the NGSL.
- **COCA / BNC frequency lists** — full-range ranking; take the **spoken** subcorpus for a speaking bot.
- **English Vocabulary Profile** (Cambridge) — maps words *and individual senses* to CEFR. The sense-level part is the valuable bit.

## Lemma, word family, or form?

- **Form**: *goes*, *going*, *went* as separate items. Too granular — inflates the list and bores the learner.
- **Lemma**: *go* covering its inflections. The right unit for teaching and for SRS cards.
- **Word family**: *nation, national, nationalise, internationally*. Right unit for measuring coverage, wrong unit for teaching a beginner, who cannot derive family members they have never met.

Use **lemmas for cards, families for coverage statistics.** And store part of speech: *record* (noun, /ˈrekɔːd/) and *record* (verb, /rɪˈkɔːd/) are two items with different stress, different level and different meaning.

## Senses, not just words

*Get* is A1. *Get* meaning "understand" is B1; "become" is A2; "annoy" (*it gets me*) is B2. A word's level is really its *sense's* level.

Minimum viable version: store one row per (lemma, pos, sense) with its own CEFR tag and example, and teach the senses in frequency order rather than dumping a dictionary entry. A learner shown eight senses of *get* learns none.

## Measuring text difficulty

Classic readability formulas (Flesch–Kincaid, Flesch Reading Ease) were built for L1 readers and measure sentence and syllable length. They are weak proxies for L2 difficulty but not useless as a coarse filter.

Better signals for L2, computable cheaply:

- **Coverage against the learner's known-word set** — the single best predictor. If >5% of tokens are unknown, the text is too hard.
- **Mean frequency rank of content words.**
- **Proportion of tokens outside the top-2000.**
- **Mean sentence length** and subordination density.

The practical rule for generated content: check the text against the learner's known list and regenerate if unknown-token share exceeds ~5–10%. This is easy, cheap and far more reliable than asking an LLM "is this B1?".

## Spacing new introductions

Do not introduce a word once and retire it. Build recurrence into the pipeline:

- New words re-appear in the *reading/listening* material of the following sessions, not only as cards.
- Target 8–12 encounters across varied contexts before considering an item known.
- Mix receptive encounters (seen in a text) with productive demands (used in a sentence). Receptive-only exposure produces vocabulary the learner recognises but cannot deploy — the classic "I understand everything but can't speak" complaint.

## A content selection pipeline

1. Take the frequency-ordered list, filtered to the learner's level band ±1.
2. Remove what the learner already knows (their card set with sufficient stability).
3. Pick N items (6–10 per session) that co-occur naturally so they can appear in one text.
4. Generate or retrieve context — a short dialogue, not isolated sentences.
5. Validate: unknown-token share ≤ ~10%, target items present, length appropriate.
6. Create cards for the target items; schedule the recurrences.

Step 5 is the one usually skipped, and it is the one that keeps generated content honest.
