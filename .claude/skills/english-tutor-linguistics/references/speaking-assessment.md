# Assessing speech

## CAF: three dimensions, measured separately

Complexity, Accuracy and Fluency trade off against each other. Push a learner toward accuracy and they slow down and simplify; push toward fluency and errors rise. Collapsing them into one "speaking score" makes normal development look like regression and gives the learner no actionable signal.

### Fluency — all computable from ASR timestamps

| Metric | Definition | Rough interpretation |
|---|---|---|
| Speech rate | syllables (or words) per minute, pauses included | A2 ≈ 80–110 wpm, B1 ≈ 110–140, B2 ≈ 140–170, native conversational ≈ 150–190 |
| Articulation rate | syllables per minute of *phonation* only | Isolates speed from hesitation |
| Mean length of run | syllables between pauses ≥ 0.25 s | Strongest single fluency correlate |
| Silent pause ratio | pause time / total time | Falls as fluency grows |
| Mid-clause pause rate | pauses inside clauses, per 100 words | More diagnostic than end-of-clause pauses, which are normal |
| Repair rate | false starts + repetitions + self-corrections per 100 words | |

The mid-clause distinction is the useful subtlety: fluent speakers pause at clause boundaries (planning the next chunk), learners pause inside clauses (searching for a word). Two speakers with identical pause ratios can be at very different levels.

Use a **0.25 s** threshold for silent pauses (0.4 s is also used in the literature — pick one and keep it, since the numbers are not comparable across thresholds).

### Accuracy

- **Errors per 100 words**, by category from the error taxonomy.
- **Percentage of error-free clauses** — less sensitive to transcription noise than a raw error count.

Weight by severity. A learner making three minor article slips is not less accurate than one producing an incomprehensible clause.

### Complexity

- **Syntactic**: clauses per AS-unit, subordination ratio, mean length of AS-unit. The **AS-unit** (Analysis of Speech unit — an independent clause with its subordinates) is the standard segmentation for spoken data; sentences do not exist in speech.
- **Lexical diversity**: use **MTLD** or **MATTR**. Do **not** use raw type-token ratio — it falls mechanically with text length, so a learner who talks longer scores lower. This mistake is extremely common and silently inverts your metric.
- **Lexical sophistication**: proportion of tokens outside the top-2000 frequency band.

## The ASR pipeline

```
voice note (OGG/OPUS)
   → ASR with word timestamps
   → fluency metrics from timestamps
   → error detection on the transcript (LLM, structured output)
   → pronunciation scoring (optional, phoneme level)
   → selection: 1–3 items
   → feedback message
```

Practical notes:

- **Get word-level timestamps.** Whisper-family models provide them; without them every fluency metric above is unavailable and you are left grading the transcript only.
- **ASR errors are not learner errors.** A transcript of accented speech contains substitutions the learner did not make. Never present a raw transcript-derived correction without a confidence filter, or the bot will confidently correct something the user said correctly. This is the fastest way to lose a user's trust.
- **Do not transcribe with a model that silently "fixes" grammar.** Some ASR post-processing normalises disfluency and grammar, which erases exactly what you want to measure. Check this on a deliberately ungrammatical sample before committing to a provider.
- **Record the audio duration and the phonation time**, not just the text. They cannot be recovered later.

## Pronunciation scoring

Two approaches, in increasing order of cost:

**1. Transcript comparison.** Have the learner read a known target, transcribe, and compute word/phoneme error rate against the reference. Cheap, works well for read-aloud drills, useless for free speech. Convert the reference to phonemes with a G2P resource (CMUdict for American English; `espeak-ng` or a neural G2P for out-of-vocabulary words) and compute edit distance at the phoneme level — **PER is far more informative than WER**, since it tells you *which sound* failed.

**2. Goodness of Pronunciation (GOP).** Force-align the audio to the expected phoneme sequence with an acoustic model and score each phoneme by its posterior probability. Gives per-phoneme scores in free speech. Heavier, needs an alignment-capable model, but it is what commercial pronunciation trainers do.

## Intelligibility over nativeness

The research consensus (Derwing & Munro; Levis) is that **accentedness, comprehensibility and intelligibility are separable**, and only the latter two matter for communication. A strongly accented speaker can be perfectly intelligible. Designing a bot that pushes toward a native accent wastes the learner's effort and is demotivating, because the goal is unreachable for most adult learners and unnecessary.

Prioritise by **functional load** — how often a contrast actually distinguishes words:

**High functional load, fix these:**
- /ɪ/ vs /iː/ — *ship/sheep*, *live/leave*, *bit/beat*
- /æ/ vs /e/ — *bad/bed*
- /l/ vs /r/ — *light/right*
- Consonant cluster simplification — *sixths*, *asked*
- **Word stress** — misplaced stress harms intelligibility more than any single segment, and is under-taught

**Low functional load, deprioritise:**
- /θ/, /ð/ → /s/, /z/, /t/, /d/ — *think* → *sink* almost never causes real confusion in context
- Precise vowel quality in unstressed syllables
- Final /r/ (rhotic vs non-rhotic) — both are standard

Getting this priority order wrong is common: bots drill *th* endlessly (it is audible and easy to detect) while ignoring the *ship/sheep* contrast that actually breaks communication.

## The Russian-L1 phonological profile

Predictable transfer, in rough priority order:

1. **/ɪ/ vs /iː/** — Russian has no short-lax /ɪ/; *ship* → *sheep*. High functional load, fix first.
2. **Final obstruent devoicing** — Russian devoices finals, so *bed* → *bet*, *dog* → *dock*, *has* → *has(s)*. High load: it neutralises minimal pairs and the plural/possessive /z/.
3. **Vowel reduction and rhythm** — Russian reduces vowels differently; English's stress-timed rhythm and pervasive schwa in unstressed syllables are usually absent, producing a syllable-timed, "even" delivery that is a major comprehensibility factor.
4. **Word stress placement** — frequently misassigned; high impact.
5. **/w/ vs /v/** — *west/vest*. Russian has /v/ but no /w/.
6. **/æ/ vs /e/** — *bad/bed*.
7. **Dark /l/** — Russian's palatalised vs velarised /l/ distribution differs; audible but moderate load.
8. **Aspiration of /p, t, k/** — unaspirated Russian stops make *pin* sound like *bin* to English ears. Moderate load, easy to teach.
9. **/θ/, /ð/** — universally noticed, low functional load. Teach it, but not before 1–4.
10. **/h/ → /x/** — mild accent marker, negligible load.

Also: Russian palatalises consonants before front vowels, which colours *see*, *tea*, *needs*. Low load, cosmetic.

## Reporting to the learner

Do not show raw metrics. Convert to something actionable:

- **One dimension per session.** "Your speech was 20% faster than last week" or "you paused less mid-sentence" — not a dashboard.
- **Compare to their own past, not to a native baseline.** Progress is motivating; a permanent gap is not.
- **One pronunciation target at a time**, with audio: their recording, the model, and a minimal pair to practise.
- **Say what improved before what did not.** A learner who records a voice message has taken a real risk; the response determines whether they do it again.
