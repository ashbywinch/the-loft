/** The identification review (stage 8) — one agreed document's people and
 *  places, read from its agreed text, each awaiting the family's word.
 *
 *  Nothing the machine read is asserted here: every entity is a proposal
 *  until the family keeps it (as a fact, or as their own guess in their own
 *  words), leaves it for later, or deletes it. The decision lands in the
 *  identity table and on the document's own mention, so the next visit
 *  shows the settled state — the document is read once, never re-read.
 */

import { el, header } from "../ui.js";
import { canGoBackInApp } from "../router.js";

/** The four dispositions — the review's vocabulary, named for the family:
 *  the statuses (proposed/estimated/confirmed) never appear as actions. */
const DISPOSITIONS = [
  ["attested", "Record as a fact"],
  ["estimated", "Record as a guess"],
  ["pending", "Leave for later"],
  ["delete", "Delete"],
];

function today() {
  return new Date().toISOString().slice(0, 10);
}

/** The document's mentions, each beside its identity record. */
function entitiesOf(state, item) {
  const rows = [];
  for (const ref of item.people ?? []) {
    rows.push({ kind: "person", ref, record: (state.people ?? []).find((person) => person.id === ref.id) });
  }
  for (const ref of item.places ?? []) {
    rows.push({ kind: "place", ref, record: (state.places ?? []).find((place) => place.id === ref.id) });
  }
  return rows;
}

function waitingCount(item) {
  return [...(item.people ?? []), ...(item.places ?? [])].filter((ref) => ref.status === "proposed").length;
}

/** One mention: the name, the proposal's own evidence, and — while it still
 *  waits — the four dispositions. */
function entityRow(state, row, onChange, decided) {
  const { kind, ref, record } = row;
  const name = record?.name ?? ref.id;
  const basis = record?.basis?.text ?? record?.note ?? "";
  const settled = decided.has(ref.id)
    ? "Left for later."
    : ref.status === "confirmed"
      ? "Recorded as a fact."
      : ref.status === "estimated"
        ? `Recorded as a guess${record?.basis?.text ? `: "${record.basis.text}"` : ""}.`
        : "";
  const card = el("div", { class: "identify-entity" }, [
    el("div", { class: "identify-name" }, name),
    el("div", { class: "card-meta" }, `${kind === "person" ? "Person" : "Place"} the document names.`),
    basis ? el("p", { class: "card-meta" }, `It says: "${basis}"`) : null,
  ]);
  if (settled) {
    card.append(el("p", { class: "card-meta" }, settled));
    return card;
  }
  const actions = el("div", { class: "chips" });
  const guessBox = el("div", { class: "identify-guess" });
  for (const [decision, label] of DISPOSITIONS) {
    actions.append(
      el(
        "button",
        {
          class: decision === "attested" ? "btn btn-primary" : "btn",
          onclick: () => {
            if (decision === "estimated") {
              revealGuess(guessBox, state, kind, ref.id, name, onChange);
              return;
            }
            onChange(kind, ref.id, decision, null);
          },
        },
        label,
      ),
    );
  }
  card.append(actions, guessBox);
  return card;
}

/** The reviewer's own words for a guess — the family's recollection is the
 *  basis, recorded verbatim, never the machine's paraphrase. */
function revealGuess(box, state, kind, entityId, name, onChange) {
  if (box.childElementCount) return;
  const words = el("textarea", {
    class: "field",
    rows: 2,
    placeholder: `What do you remember about ${name}?`,
  });
  const save = el("button", { class: "btn btn-primary" }, "Save the guess");
  save.addEventListener("click", () => {
    const text = words.value.trim();
    if (!text) {
      words.focus();
      return;
    }
    const basis = { text, by: state.me?.name ?? "the reviewer", when: today() };
    onChange(kind, entityId, "estimated", basis);
  });
  box.append(words, save);
}

/** The server's answer merged into the loaded state: the document as it now
 *  stands, and the identity records the mentions name. */
function mergeAnswer(state, body) {
  if (body?.item) {
    const index = (state.items ?? []).findIndex((item) => item.id === body.item.id);
    if (index >= 0) state.items[index] = body.item;
    else state.items = [...(state.items ?? []), body.item];
  }
  mergeRecords(state, "people", body?.people);
  mergeRecords(state, "places", body?.places);
}

function mergeRecords(state, key, records) {
  for (const record of records ?? []) {
    const list = state[key] ?? [];
    const index = list.findIndex((entry) => entry.id === record.id);
    if (index >= 0) list[index] = record;
    else list.push(record);
    state[key] = list;
  }
}

async function identify(itemId) {
  try {
    const res = await fetch(`/api/identify/document/${encodeURIComponent(itemId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("identify: the document could not be read", error);
    return null;
  }
}

async function decide(itemId, kind, entityId, decision, basis) {
  try {
    const res = await fetch("/api/identify/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, kind, entity_id: entityId, decision, basis }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("identify: the decision did not save", error);
    return null;
  }
}

/** The decision's local effect — the server's answer is authoritative: the
 *  mention takes the record's status (a person already confirmed stays a
 *  fact), and a delete removes the mention and the proposal. */
function applyDecision(state, itemId, kind, entityId, decision, record) {
  const item = (state.items ?? []).find((entry) => entry.id === itemId);
  if (!item) return;
  const key = kind === "person" ? "people" : "places";
  const refs = item[key] ?? [];
  if (decision === "delete") {
    item[key] = refs.filter((ref) => ref.id !== entityId);
    state[key] = (state[key] ?? []).filter((entry) => entry.id !== entityId);
  } else if (decision !== "pending") {
    const status = record?.status ?? "confirmed";
    item[key] = refs.map((ref) => (ref.id === entityId ? { ...ref, status } : ref));
  }
}

export function render(main, ctx, state) {
  const itemId = ctx.arg;
  const loaded = (state.items ?? []).find((entry) => entry.id === itemId);
  main.append(header("Identify people/places", state, canGoBackInApp() ? true : "Identify"));
  if (!loaded) {
    main.append(el("p", { class: "empty" }, "Not found."));
    return;
  }
  const note = el("p", { class: "card-meta" }, "Reading the document for the people and places it names…");
  const list = el("div", { class: "identify-entities" });
  const section = el("section", { class: "block identify" }, [
    el("h2", { class: "block-title" }, loaded.title || loaded.id),
    note,
    list,
    el("details", { class: "identify-text" }, [
      el("summary", {}, "The document's text"),
      el("pre", {}, loaded.transcription ?? ""),
    ]),
  ]);
  main.append(section);
  // the mentions this visit has settled — "left for later" changes nothing
  // in the table, so the row must not re-ask it twice in one visit
  const decided = new Set();

  /** The document as the loaded state now holds it (a server answer
   *  replaces the entry, so the boot copy is never the one rendered). */
  const current = () => (state.items ?? []).find((entry) => entry.id === itemId) ?? loaded;

  const show = () => {
    const item = current();
    const rows = entitiesOf(state, item);
    const waiting = waitingCount(item);
    note.textContent = !item.identified
      ? "Reading the document for the people and places it names…"
      : waiting
        ? `${waiting} ${waiting === 1 ? "entity" : "entities"} waiting for your word.`
        : "Every entity is settled — nothing more to identify here.";
    list.replaceChildren(...rows.map((row) => entityRow(state, row, onChange, decided)));
    if (item.identified && !waiting && !rows.length) {
      list.append(
        el("p", { class: "empty" }, "The document names no people or places the archive can identify."),
      );
    }
  };

  const onChange = async (kind, entityId, decision, basis) => {
    note.textContent = "Saving…";
    const answer = await decide(itemId, kind, entityId, decision, basis);
    if (!answer) {
      note.textContent = "That didn't save — try again.";
      return;
    }
    if (!answer.entity?.gone) {
      mergeRecords(state, kind === "person" ? "people" : "places", [answer.entity]);
    }
    applyDecision(state, itemId, kind, entityId, decision, answer.entity);
    if (decision === "pending") decided.add(entityId);
    show();
  };

  show();
  identify(itemId).then((body) => {
    if (!body) {
      note.textContent = "The document could not be read — try again later.";
      return;
    }
    mergeAnswer(state, body);
    show();
  });
}
