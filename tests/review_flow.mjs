/**
 * The review card's interaction, run for real.
 *
 * The page's rules are not decoration — they decide what gets written to a
 * learner's schedule. "I pressed знаю, saw I was wrong, pressed не знаю" must
 * record a lapse, and a premature "знаю" must not archive the word on the way
 * past. Reading the file and hoping is not a test of that.
 *
 * So the page's own <script> is extracted and executed against a DOM small
 * enough to be obviously correct. Nothing is reimplemented: if review.html
 * changes, this runs the change.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "..", "bot", "webapp", "review.html"), "utf8");
const source = html.slice(
  html.lastIndexOf("<script>") + "<script>".length,
  html.lastIndexOf("</script>"),
);

// --- the smallest DOM the page can run on ---------------------------------

const sent = [];
const elements = new Map();

function element(id) {
  if (!elements.has(id)) {
    const classes = new Set();
    elements.set(id, {
      id,
      textContent: "",
      innerHTML: "",
      style: {},
      classList: {
        add: (c) => classes.add(c),
        remove: (c) => classes.delete(c),
        toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
        contains: (c) => classes.has(c),
      },
      setAttribute() {},
      removeAttribute() {},
      onclick: null,
    });
  }
  return elements.get(id);
}

const cards = [
  { id: 1, word: "stubborn", translation: "упрямый", image: "", pos: "adjective" },
  { id: 2, word: "queue", translation: "очередь", image: "", pos: "noun" },
  { id: 3, word: "grocery", translation: "продукты", image: "", pos: "noun" },
];

globalThis.window = {};
globalThis.document = { getElementById: element, documentElement: { dataset: {} } };
globalThis.matchMedia = () => ({ matches: false });
globalThis.Image = class {
  set src(_) {}
};
globalThis.location = { reload() {} };
globalThis.fetch = async (path, options = {}) => {
  if (path === "/api/review") {
    return { ok: true, json: async () => ({ cards: structuredClone(cards), archived: 0 }) };
  }
  if (path === "/api/review/answer") {
    sent.push(JSON.parse(options.body));
    return { ok: true, json: async () => ({}) };
  }
  return { ok: true, json: async () => ({}) };
};

await import("node:vm").then(({ runInThisContext }) => runInThisContext(source));
// The page's start() is async; let its first fetch settle.
await new Promise((resolve) => setTimeout(resolve, 0));

const no = element("no");
const yes = element("yes");
const answer = element("answer");
const verdict = element("verdict");

// --- what the learner asked for -------------------------------------------

assert.equal(element("word").textContent, "stubborn", "first card is up");
assert.equal(answer.textContent, "", "the answer is hidden until they commit to a guess");
assert.equal(yes.textContent, "Знаю");

// Pressing "знаю" must STILL show the translation — the whole request.
yes.onclick();
assert.equal(answer.textContent, "упрямый", "знаю reveals the answer too");
assert.equal(yes.textContent, "Дальше →", "green becomes next once the answer is up");
assert.equal(no.textContent, "Не знал", "red stays live so a wrong знаю can be undone");
assert.match(verdict.textContent, /архив/, "it says what next will do");
assert.equal(sent.length, 0, "nothing is recorded while the verdict can still change");

// Still on the same card: seeing the answer must not move it along.
assert.equal(element("word").textContent, "stubborn");

// Now the correction: they were wrong after all.
no.onclick();
assert.equal(element("word").textContent, "stubborn", "correcting does not skip the card");
assert.equal(no.classList.contains("chosen"), true, "the choice made is visibly the one made");
assert.match(verdict.textContent, /пораньше/, "and next will now record a miss");
assert.equal(sent.length, 0, "still nothing recorded");

// Moving on records the corrected verdict, not the first impulse.
yes.onclick();
assert.deepEqual(
  sent.map(({ card, known }) => ({ card, known })),
  [{ card: 1, known: false }],
  "a corrected знаю is recorded as a miss",
);
assert.equal(element("word").textContent, "queue", "and the next card is up");
assert.equal(answer.textContent, "", "with its answer hidden again");
assert.equal(no.classList.contains("chosen"), false, "and no verdict carried over");

// An uncorrected "знаю" archives.
yes.onclick();
yes.onclick();
assert.deepEqual(sent.at(-1), { card: 2, known: true, initData: "" });
assert.match(element("archive").innerHTML, /В архиве 1/, "the archive count follows");

// "Не знаю" straight away: reveal, then move on, recorded as a miss.
no.onclick();
assert.equal(answer.textContent, "продукты");
assert.equal(no.classList.contains("chosen"), true);
yes.onclick();
assert.deepEqual(sent.at(-1), { card: 3, known: false, initData: "" });

assert.equal(element("done-title").textContent, "Готово 👌", "the deck finishes");

console.log(`review flow: ${sent.length} answers recorded, all as chosen`);
