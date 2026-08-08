/** The import review (user, 2026-08-07) — a chat, not a form (user,
 *  2026-08-08): the pending people are confirmed in the review
 *  conversation, and the kinship is specific, never a bare "cousin".
 *  Tapping Review opens the chat for one person: is she family? — and when
 *  she is, IN WHAT WAY ("mum's cousin on Fern's side" resolves to a precise
 *  term through the assistant). The one chat surface (app/chat.js) is
 *  reused — nothing is coded twice. */

import { el, header } from "../ui.js";
import { proposedPeople } from "../data.js";
import { chatBox } from "../chat.js";
import { navigate } from "../router.js";

// the specific kinship terms offered as quick replies, keyed by the keyword
// the import's relation text carries — the narrator can also say it in their
// own words and the assistant resolves the exact term
const TERM_OPTIONS = {
  cousin: ["first cousin", "first cousin once removed", "first cousin twice removed", "second cousin", "second cousin once removed", "cousin-in-law"],
  aunt: ["aunt", "uncle", "great-aunt", "great-uncle"],
  uncle: ["uncle", "aunt", "great-uncle", "great-aunt"],
  grandmother: ["grandmother", "great-grandmother"],
  grandfather: ["grandfather", "great-grandfather"],
  sister: ["sister", "half-sister", "stepsister"],
  brother: ["brother", "half-brother", "stepbrother"],
  wife: ["wife", "ex-wife"],
  husband: ["husband", "ex-husband"],
  mother: ["mother", "stepmother", "adoptive mother"],
  father: ["father", "stepfather", "adoptive father"],
  daughter: ["daughter", "stepdaughter", "adopted daughter"],
  son: ["son", "stepson", "adopted son"],
};

const DEFAULT_TERMS = [
  "wife",
  "husband",
  "mother",
  "father",
  "sister",
  "brother",
  "daughter",
  "son",
  "grandmother",
  "grandfather",
  "aunt",
  "uncle",
  "first cousin",
  "first cousin once removed",
  "niece",
  "nephew",
];

function optionsFor(relation) {
  const text = String(relation ?? "").toLowerCase();
  for (const [keyword, terms] of Object.entries(TERM_OPTIONS)) {
    if (text.includes(keyword)) return terms;
  }
  return DEFAULT_TERMS;
}

export function render(main, ctx, state) {
  const session = (state.imports ?? []).find((s) => s.id === ctx.arg);
  if (!session) {
    main.append(header("The import", state), el("p", { class: "empty" }, "Not found."));
    return;
  }
  main.append(header(session.title, state));
  const pending = proposedPeople(state);
  if (!pending.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h2", { class: "block-title" }, "Everything is confirmed"),
        el("p", { class: "memories-note" }, "Nothing is waiting — the import is done."),
      ]),
    );
    return;
  }
  main.append(
    el("section", { class: "block import-pending" }, [
      el("h2", { class: "block-title" }, `${pending.length} ${pending.length === 1 ? "person" : "people"} awaiting confirmation`),
      el(
        "div",
        { class: "cast-grid" },
        pending.map((person) =>
          el("div", { class: "cast-card" }, [
            el("div", { class: "cast-name" }, person.name),
            el("div", { class: "cast-relation clamp-2" }, person.relation ?? ""),
            el("div", { class: "confirm-actions" }, [
              el("button", { class: "btn btn-primary", onclick: () => reviewChat(state, person) }, "Review"),
            ]),
          ]),
        ),
      ),
    ]),
  );
}

// -- the review conversation -------------------------------------------------

function reviewChat(state, person) {
  const overlay = el("div", { class: "sheet-overlay" });
  const sheet = el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": `Review ${person.name}` });
  const chat = chatBox();
  const close = () => overlay.remove();
  const head = el("div", { class: "sheet-head" }, [
    el("button", { class: "btn", "aria-label": "Close", onclick: close }, "‹"),
    el("div", { class: "sheet-title" }, `Reviewing ${person.name}`),
  ]);
  const body = el("div", { class: "sheet-body" });
  sheet.append(head, body);
  body.append(chat.node);
  overlay.append(sheet);
  document.body.append(overlay);

  const imported = person.relation ? `the import's record: '${person.relation}'` : "no relation on the import's record";
  chat.addAssistant(`${person.name} — ${imported}. Is she family?`);
  chat.setQuickReplies([
    { label: "Yes — she's family", primary: true, onClick: () => askHow(chat, state, person, close) },
    { label: "No — dismiss her", onClick: () => dismissPerson(state, person, chat, close) },
  ]);

  chat.onSend((text) => resolveRelation(chat, state, person, text, close));
}

function askHow(chat, state, person, close) {
  chat.addAssistant(
    `In what way is she family? ${person.relation ? `The import says '${person.relation}' — ` : ""}pick the closest term, or say it in your own words — "mum's cousin on Fern's side" works.`,
  );
  chat.setQuickReplies([
    ...optionsFor(person.relation).map((term) => ({ label: term, onClick: () => confirmWith(state, person, term, chat, close) })),
    { label: "Something else — I'll say it", onClick: () => chat.swapInput(el("textarea", { class: "field", rows: 1, placeholder: "In what way? (e.g. 'mum's cousin on Fern's side')" })) },
  ]);
}

/** The narrator typed the kinship in their own words — the assistant
 *  resolves it to a precise term against the known family, then confirms. */
async function resolveRelation(chat, state, person, text, close) {
  chat.addUser(text);
  chat.setQuickReplies([]);
  chat.setBusy(true);
  try {
    const res = await fetch("/api/review/relate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ person_id: person.id, text }),
    });
    if (!res.ok) {
      chat.addAssistant("Sorry — I couldn't work out the exact relationship from that. Try one of the terms, or say it another way?");
      chat.setQuickReplies(optionsFor(person.relation).map((term) => ({ label: term, onClick: () => confirmWith(state, person, term, chat, close) })));
      return;
    }
    const body = await res.json();
    const relation = body.note ? `${body.term} (${body.note})` : body.term;
    chat.addAssistant(`So she's your ${relation}. Confirming that.`);
    await confirmWith(state, person, relation, chat, close);
  } catch (error) {
    console.error("import review: relation resolution failed", error);
    chat.addAssistant("Sorry — the assistant couldn't be reached. Try one of the terms instead?");
    chat.setQuickReplies(optionsFor(person.relation).map((term) => ({ label: term, onClick: () => confirmWith(state, person, term, chat, close) })));
  } finally {
    chat.setBusy(false);
  }
}

async function confirmWith(state, person, relation, chat, close) {
  chat.setBusy(true);
  const ok = await confirmPerson(state, person, relation);
  if (ok) {
    chat.addAssistant(`${person.name} is confirmed — ${relation}.`);
    setTimeout(close, 900); // let the confirmation land, then back to the list
  } else {
    chat.addAssistant("That didn't save — try again?");
    chat.setBusy(false);
  }
}

/** Confirm: the person becomes family (status drops; confirmed records omit
 *  it) with the SPECIFIC kinship the review settled on. The server
 *  supersedes the archive, republishes, and returns the updated person —
 *  merge it and re-render without a reload. Returns whether it saved. */
async function confirmPerson(state, person, relation) {
  try {
    const res = await fetch("/api/people/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: person.id, relation }),
    });
    if (!res.ok) return false;
    const body = await res.json();
    const updated = body.person;
    const idx = state.people.findIndex((p) => p.id === updated.id);
    if (idx >= 0) state.people[idx] = updated;
    else state.people.push(updated);
    // the last pending person completes the session — the server agrees, but
    // the client's merged state must too, or the card lingers until a reload
    if (proposedPeople(state).length === 0) {
      state.imports = (state.imports ?? []).map((s) => (s.status === "pending" ? { ...s, status: "reviewed" } : s));
    }
    navigate(location.hash); // re-render the current route with the merged state
    return true;
  } catch (error) {
    console.error("import review: confirm failed", error);
    return false;
  }
}

/** Dismiss: dropped = gone (the proposed/confirmed seam). The person and
 *  their relationships leave the archive. */
async function dismissPerson(state, person, chat, close) {
  chat.setBusy(true);
  try {
    const res = await fetch("/api/people/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: person.id }),
    });
    if (!res.ok) throw new Error(`dismiss failed: ${res.status}`);
    state.people = state.people.filter((p) => p.id !== person.id);
    state.relationships = (state.relationships ?? []).filter((r) => r.a !== person.id && r.b !== person.id);
    if (proposedPeople(state).length === 0) {
      state.imports = (state.imports ?? []).map((s) => (s.status === "pending" ? { ...s, status: "reviewed" } : s));
    }
    chat.addAssistant(`Dismissed — ${person.name} is out of the archive.`);
    navigate(location.hash);
    setTimeout(close, 900);
  } catch (error) {
    console.error("import review: dismiss failed", error);
    chat.addAssistant("That didn't save — try again?");
    chat.setBusy(false);
  }
}
