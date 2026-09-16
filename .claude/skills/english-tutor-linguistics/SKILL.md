---
name: english-tutor-linguistics
description: Applied linguistics and language-teaching methodology for building an English-learning product — CEFR levelling, vocabulary selection by frequency, spaced repetition (SM-2/FSRS), error taxonomies and corrective feedback, speaking assessment (fluency/accuracy/complexity), pronunciation scoring, and prompting an LLM to act as a tutor. Use this skill whenever the task involves what the bot teaches or how it responds as a teacher: designing exercises or lessons, picking which words to teach, scheduling reviews, correcting a learner's sentence, grading speech, estimating a level, or writing the prompt that generates feedback — not just when the user says "linguistics" or "pedagogy".
---

# Teaching English, computationally

A language bot is two products stacked: software, and a curriculum. The software part is solved by the other skills here. This one covers the part that decides whether anyone actually learns — and it has real research behind it, so the defaults below are not aesthetic preferences.

The single most useful frame: **the bot's job is to maximise the number of successful retrievals of level-appropriate language per minute of user attention.** Every design decision below serves that.

## Level: CEFR, used properly

CEFR (A1 → C2) describes what a learner *can do*, not what grammar they have covered. "B1" means things like *can describe experiences, events, dreams and ambitions and briefly give reasons for opinions* — a functional claim.

Practical consequences:

- **Level content by can-do statements, not by grammar checklists.** "Present perfect" is not a level; "can talk about past experience without specifying when" is.
- **A user's level is not one number.** Receptive level runs roughly one band ahead of productive; listening and speaking diverge widely. Store at least a productive and a receptive estimate, and never let a single placement test set a permanent label.
- **Sub-levels matter more than you expect.** A2 to B1 is a year of work for most learners. If everything is tagged at whole-band granularity, half your content will feel wrong. Use A2.1/A2.2 or a continuous score mapped onto bands.
- **Aim at i+1.** Content slightly above current level drives acquisition; content far above it produces frustration, and content at level produces comfort but little gain. Concretely: ~90–95% known words in input, one new structure at a time.

Approximate productive vocabulary sizes per band — useful for sanity checks, not for claims to users: A1 ≈ 500–600 words, A2 ≈ 1 000–1 500, B1 ≈ 2 000–2 500, B2 ≈ 4 000–5 000, C1 ≈ 8 000, C2 ≈ 16 000. These vary by source; treat as order-of-magnitude.

## Vocabulary: teach by frequency, not by topic

Topic-based word lists ("at the airport", "colours") feel organised and waste the learner's time — they mix a high-frequency word like *leave* with *boarding pass*, which a learner may need twice a decade.

The coverage facts that should drive selection:

- The most frequent ~2 000 word families cover roughly **80–85%** of general text and considerably more of everyday speech.
- **95% coverage** is about the minimum for guessing unknown words from context; **98%** is needed for comfortable unassisted reading (Nation).
- Getting from 95% to 98% costs several thousand more word families. That gap *is* the B1→C1 journey.

So: order acquisition by corpus frequency, filtered to the learner's level, and only then group into topics for presentation. For a **speaking** bot, use a spoken-frequency corpus (spoken sections of COCA/BNC) rather than a written one — written frequency over-weights *however*, *furthermore*, *approximately* and under-weights *guy*, *stuff*, *kind of*, which is what conversation actually contains.

A word is not learned on first meeting. Expect **8–12 meaningful encounters**, spread over time, in varied contexts. Design the content pipeline so a newly introduced word recurs in later material rather than being retired after its lesson.

Details — lemma vs word family, which lists to use, sense-level levelling, how to measure text difficulty: `references/cefr-and-vocabulary.md`.

## Spaced repetition: the scheduling core

Two effects do the heavy lifting, and they are among the most robust findings in learning science:

- **Testing effect** — retrieving an item from memory strengthens it far more than re-reading it. A card the user *tries* to answer beats a card they are shown.
- **Spacing effect** — the same total study time distributed over days beats it massed into one session, and the gain grows with the retention interval you care about.

Both mean the bot should ask, not tell, and should ask again later.

Which algorithm:

- **SM-2** — the Anki classic. ~40 lines, no training data, easy to reason about. Correct choice for v1.
- **FSRS** — models memory as difficulty/stability/retrievability, fits parameters to real review logs, and reliably beats SM-2 on review efficiency once you have data. Correct choice once you have a few thousand reviews per user cohort.

Both are specified with working code in `references/srs-algorithms.md`, including the decision of *when* the switch is worth making and how to keep the schema compatible with both.

Two scheduling decisions that matter more than the algorithm:

- **Cap the daily queue.** An uncapped backlog after a week away shows 400 due cards and the user quits. Cap, and reschedule the overflow.
- **Interleave item types.** Blocked practice (ten vocabulary cards, then ten grammar) feels easier and transfers worse than mixing them. Shuffle across skills within a session.

## Correction: what to fix, and how

The instinct to correct every error is the most common failure mode of an LLM-powered tutor. It is demotivating, it exceeds working memory, and it does not work.

**Select.** At most **1–3** corrections per learner turn. Priority order:

1. Errors that break comprehensibility.
2. Errors in structures at or just below the learner's level (they are ready to fix these).
3. High-frequency, systematic errors — the same one recurring beats a one-off slip.

Ignore the rest, silently. A learner who is understood should feel understood.

**Choose the feedback type deliberately.** From the classic taxonomy (Lyster & Ranta), the useful split is:

- **Recast** — you restate correctly in the flow of conversation ("You went there yesterday, right?"). Low interruption, but learners often do not notice it, so uptake is weak.
- **Prompts** — elicitation ("You ___ there yesterday?"), metalinguistic hints ("past tense here"), clarification requests. Higher interruption, much higher repair rate, because the learner produces the correction themselves.

For a bot, the effective pattern is **prompt first, reveal second**: give a hint, let them retry once, then show the correction with a one-line explanation. That converts a correction into a retrieval, which is the thing that actually builds memory.

**Tag everything.** Every correction gets a category from a fixed taxonomy (articles, tense/aspect, prepositions, agreement, word order, word choice, plurals…). Tagged history is what lets the bot say "articles are still your weak spot" and generate targeted practice — and it is the most valuable data the product accumulates. The full taxonomy, and the Russian-L1 error profile that this project specifically needs, is in `references/error-correction.md`.

## Speaking assessment

Do not reduce speaking to "was the transcript correct". The standard framework is **CAF — Complexity, Accuracy, Fluency** — and the three trade off against each other: a learner told to be accurate becomes slower and simpler. Measure them separately or you will misread progress as regression.

- **Fluency** — speech rate (syllables/min), mean length of run between pauses, silent-pause frequency, repair rate (false starts, self-corrections). All computable from ASR timestamps, no human needed.
- **Accuracy** — errors per 100 words, percentage of error-free clauses.
- **Complexity** — clauses per AS-unit, subordination ratio; lexical diversity via **MTLD or MATTR** (not raw type-token ratio, which is length-dependent and will make longer answers look worse).

**Pronunciation**: score intelligibility, not nativeness. The research consensus (Derwing & Munro, Levis) is that accent and comprehensibility are separable, and only the latter matters. Use the **functional load** principle to prioritise: a /ɪ/–/iː/ confusion (*ship/sheep*) changes meaning constantly; a dental-fricative substitution (*think* → *sink*) rarely causes real misunderstanding. Correcting the second while ignoring the first is a common and backwards choice.

Metrics, formulas, ASR-based pipelines, and the Russian-L1 pronunciation priority list: `references/speaking-assessment.md`.

## The LLM as tutor

An LLM generating feedback needs the same discipline as a human teacher, imposed through the prompt.

Non-negotiables:

- **Separate the roles.** Conversation partner and assessor are different jobs with opposite instincts (keep talking vs. stop and fix). Run them as separate calls, or separate clearly-delimited sections of one structured output.
- **Demand structured output.** Free-text feedback cannot be tagged, stored, or turned into practice. Require JSON with `original_span`, `correction`, `category`, `severity`, `explanation`.
- **Require grounding.** The model must quote the exact span it is correcting. This alone kills most hallucinated corrections.
- **Allow "no errors".** A model asked to find errors will find them. State explicitly that a correct sentence returns an empty list, and that natural-but-informal language is not an error.
- **Cap the correction count in the prompt**, and give the selection criteria above — otherwise you get seven corrections on a five-word sentence.
- **Level-cap the bot's own speech.** The tutor's replies must sit at the learner's level +1, not at the model's default register. Without this instruction, a B1 learner gets C2 English back and understands nothing.

Working prompt templates, rubrics with anchors, and the level-estimation prompt: `references/llm-tutor-prompts.md`.

## Session design

A session that works, in order:

1. **Warm-up retrieval** — 2–3 items due for review. Starts with success, primes the language.
2. **New material** — one concept or a small word set, in context, never a bare list.
3. **Productive use** — they say or write something using it. This is where learning happens; a session without production is a session of recognition only.
4. **Feedback** — selected, prompted first, tagged.
5. **Close on a win** — an easy item, a visible number (words reviewed, streak), one concrete next step.

Keep it **5–15 minutes**. Daily short beats weekly long, for both the spacing effect and retention of the user.

## Metrics that are not vanity

- **Retention rate at review** — % of due cards answered correctly. Target ~85–90%. Much higher means intervals are too short and you are wasting the user's time; much lower means too long, or the material is above level.
- **Productive turns per session** — how often the learner actually generated language.
- **Repeat error rate by category** — is tagged feedback changing behaviour? This is the real efficacy measure.
- **Days active in last 28** — the only engagement number that correlates with learning.

Total messages sent, words "seen", and time in app are vanity metrics. A bot can maximise all three while teaching nothing.

## Reference files

- `references/cefr-and-vocabulary.md` — CEFR can-do levelling, frequency lists, lemma vs word family, text difficulty measurement, content selection pipeline.
- `references/srs-algorithms.md` — SM-2 and FSRS with implementations, queue management, when to switch, schema compatibility.
- `references/error-correction.md` — error taxonomy for tagging, feedback-type selection, the Russian-L1 error profile.
- `references/speaking-assessment.md` — CAF metrics and formulas, ASR pipeline, pronunciation scoring, functional load, Russian-L1 phonological priorities.
- `references/llm-tutor-prompts.md` — prompt templates for correction, conversation, and level estimation; rubrics; failure modes.
