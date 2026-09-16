# Error taxonomy and corrective feedback

## The tagging taxonomy

Every correction stored should carry a category from a fixed, small set. Small matters: 12 categories that get used beat 60 that get applied inconsistently.

| Category | Covers | Example |
|---|---|---|
| `article` | a/an/the, zero article | *I went to ~~the~~ school by ∅ bus* |
| `tense_aspect` | tense choice, perfect/progressive | *I ~~live~~ have lived here since 2020* |
| `agreement` | subject–verb, pronoun | *He ~~go~~ goes* |
| `preposition` | prepositional choice/omission | *depend ~~from~~ on* |
| `word_order` | constituent order, adverb placement | *~~I know what is it~~ I know what it is* |
| `word_choice` | wrong lexical item, collocation | *~~make~~ do homework* |
| `word_form` | derivation, part of speech | *~~success~~ successful project* |
| `plural_countability` | number, countable/uncountable | *~~informations~~ information* |
| `modality` | modal verb choice | *~~must~~ have to* |
| `conditional` | conditional structures | mixed conditionals |
| `pronunciation` | spoken only | see the speaking reference |
| `spelling` | written only | |
| `register` | formality mismatch | *Hey* in a cover letter |

Also store **severity**: `blocking` (meaning is lost), `noticeable` (understood, clearly non-native), `minor` (natural speakers vary). Severity drives selection, and it is what stops the bot from treating a missing article and an incomprehensible sentence as equal.

Store the span, not just the sentence: `original_span`, `correction`, `category`, `severity`, `explanation`. Spans are what let you highlight inline and what let a model's claim be verified.

## Selection: what to correct

Correcting everything is the default failure of an LLM tutor and it is genuinely counterproductive — it exceeds working memory, it demotivates, and learners cannot act on eight simultaneous instructions.

**Correct at most 1–3 items per learner turn**, chosen by:

1. **Blocking severity** — anything that breaks comprehension.
2. **Level readiness** — errors in structures at or just below the learner's current level. A learner who has not met the present perfect cannot "fix" it; flagging it teaches nothing. This is the single most-ignored selection criterion.
3. **Systematicity** — an error that recurs in their history beats a one-off slip. A slip corrects itself; a systematic error is a gap in the interlanguage.

Let the rest pass. Silently. A learner who is understood should feel understood, and a conversation interrupted every sentence stops being a conversation.

## Feedback types, and which to use

The standard taxonomy (Lyster & Ranta) with the bit that matters for design:

| Type | What it is | Uptake |
|---|---|---|
| **Recast** | You restate correctly in flow: *"Ah, you went there yesterday!"* | Low — often heard as agreement, not correction |
| **Explicit correction** | *"Not 'goed' — 'went'."* | High clarity, interrupts flow |
| **Elicitation** | *"You ___ there yesterday?"* | High — learner produces the fix |
| **Metalinguistic clue** | *"That's an irregular verb."* | High |
| **Clarification request** | *"Sorry, you did what?"* | Medium; also trains repair |
| **Repetition** | Echo the error with rising intonation | Medium |

The pattern that works for a bot — because it converts correction into retrieval, which is what builds memory:

1. **Prompt**: hint at the location and type without giving the answer. *"Almost — check the verb tense."*
2. **Retry**: let them attempt once.
3. **Reveal**: if still wrong, give the correction plus one short explanation and one extra example.
4. **Log**: tag it, and schedule a targeted item.

During **free conversation**, prefer recasts and keep the conversation alive; collect errors silently and deliver the selected 1–3 in a **post-session debrief**. Fluency practice and accuracy practice are different activities, and interrupting the first with the second destroys it.

## Explanations

- **One rule, one line.** "Use *the* when both of us know which one you mean." Not a grammar-book paragraph.
- **A contrasting pair beats a rule.** *"I saw a dog"* (new) vs *"I saw the dog"* (the one we discussed) teaches more than any formulation of the article rule.
- **In the learner's L1 below B1**, in English above it. A metalinguistic explanation the learner cannot parse is noise.
- **Never invent a rule to justify a correction.** If something is idiomatic rather than rule-governed, say so: *"Both are grammatical; native speakers just say 'do homework'."*

## Turning errors into practice

A tagged error history is the most valuable data the product holds. Use it:

- When a category crosses a threshold (say 3 occurrences in 10 turns), generate a **focused micro-drill** for it — 3–5 items, in context, in the next session.
- Track **repeat rate per category over time**. That is the real efficacy metric: if article errors are not declining after twenty corrections, the feedback approach is wrong, not the learner.
- Surface it honestly: *"Articles came up 4 times this week — want a 3-minute drill?"* Naming the pattern is itself instructive; learners often do not perceive their own systematic errors.

## The Russian-L1 error profile

This project's learners are predominantly Russian speakers, and L1 transfer makes their errors highly predictable. Pre-tagging these improves both detection and explanation quality.

**Articles** — Russian has none, so this is the dominant, most persistent error category, and it stays through C1. Expect omission (*I am ∅ student*), and over-correction once taught (*the Russia*). Do not try to fix articles in one lesson; they need spread exposure over months.

**Aspect and tense** — Russian encodes perfective/imperfective aspect but has three tenses; English has twelve-ish forms. Predictable results: present simple where present perfect is needed (*I live here since 2020*), present continuous avoided or overused, past simple where present perfect belongs (*I already did it*).

**Copula omission** — Russian drops present-tense *be* (*Он студент*), so *He ∅ student* appears at A1–A2.

**Prepositions** — no clean mapping. *на/в* → in/on/at collapses; *depend from* (← *зависеть от*), *different from/than*, *on the picture* (← *на картинке*).

**Word order** — Russian word order is information-structural and flexible; English is rigid. Expect embedded-question inversion (*I don't know where is he*), and adverb misplacement (*I very like it* ← *мне очень нравится*).

**Countability** — *information, advice, money, news, knowledge* are countable or pluralisable in Russian: *informations*, *advices*, *many money*.

**Double negation** — *I don't know nothing*, grammatical in Russian.

**Verbs of possession/state** — *I have 25 years* patterns, *It seems to me* overuse, *I am agree* (← *я согласен*, an adjective in Russian).

**Politeness register** — Russian directness maps to English imperatives that read as rude (*Give me the report*), and modal hedging (*could you possibly*, *I was wondering if*) is under-used. This is a `register` tag, and it is worth teaching explicitly because the consequence is social rather than grammatical, so it is never self-corrected.

**False friends** — *actually* (≠ *актуально*), *magazine* (≠ *магазин*), *sympathetic* (≠ *симпатичный*), *accurate* (≠ *аккуратный*), *fabric* (≠ *фабрика*), *intelligent* (≠ *интеллигентный*), *normally* (≠ *нормально*).

Pronunciation transfer is covered in `speaking-assessment.md`.
