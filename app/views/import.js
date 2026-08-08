/** The import review (user, 2026-08-07) — the review IS the chat (user,
 *  2026-08-08): opening the session's review starts the conversation about
 *  the unfinished doc import and walks through the pending people one at a
 *  time. No list of people with review buttons — the kinship asked for is
 *  specific, never a bare "cousin", and the narrator can say it in their
 *  own words ("mum's cousin on Fern's side") for the assistant to resolve.
 *  The one chat surface (app/chat.js) is reused — nothing is coded twice. */

import { el, header } from "../ui.js";
import { proposedPeople } from "../data.js";
import { chatBox } from "../chat.js";

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
      reviewSession(state),
    ]),
  );
}

// -- the review conversation — one chat walks the whole session --------------

function reviewSession(state) {
  const chat = chatBox();
  const wrap = el("div", { class: "import-review" });
  wrap.append(chat.node);

  let person = null;

  const askFamily = (p) => {
    person = p;
    const imported = p.relation ? `the import's record: '${p.relation}'` : "no relation on the import's record";
    chat.addAssistant(`${p.name} — ${imported}. Is she family?`);
    chat.setQuickReplies([
      { label: "Yes — she's family", primary: true, onClick: () => askHow(p) },
      { label: "No — dismiss her", onClick: () => dismiss(p) },
    ]);
  };

  const askHow = (p) => {
    chat.addAssistant(
      `In what way is she family? ${p.relation ? `The import says '${p.relation}' — ` : ""}pick the closest term, or say it in your own words — "mum's cousin on Fern's side" works.`,
    );
    chat.setQuickReplies([
      ...optionsFor(p.relation).map((term) => ({ label: term, onClick: () => confirmWith(p, term) })),
      { label: "Something else — I'll say it", onClick: () => chat.swapInput(el("textarea", { class: "field", rows: 1, placeholder: "In what way? (e.g. 'mum's cousin on Fern's side')" })) },
    ]);
  };

  const advance = () => {
    chat.setBusy(false); // the success paths never cleared busy — the next
    // person's chips stayed hidden and the walkthrough dead-ended (bot
    // review, PR #10, 2026-08-08)
    const pending = proposedPeople(state);
    if (!pending.length) {
      chat.addAssistant("That's everyone — the document import is complete. The tree now shows the confirmed family.");
      chat.setQuickReplies([]);
      return;
    }
    askFamily(pending[0]);
  };

  const confirmWith = async (p, relation) => {
    chat.setBusy(true);
    const ok = await confirmPerson(state, p, relation);
    if (ok) {
      chat.addAssistant(`${p.name} is confirmed — ${relation}.`);
      advance();
    } else {
      chat.addAssistant("That didn't save — try again?");
      chat.setBusy(false);
    }
  };

  const dismiss = async (p) => {
    chat.setBusy(true);
    const ok = await dismissPerson(state, p);
    if (ok) {
      chat.addAssistant(`Dismissed — ${p.name} is out of the archive.`);
      advance();
    } else {
      chat.addAssistant("That didn't save — try again?");
      chat.setBusy(false);
    }
  };

  /** The narrator typed the kinship in their own words — the assistant
   *  resolves it to a precise term against the known family, then confirms. */
  const resolveRelation = async (text) => {
    const p = person;
    if (!p) return;
    chat.addUser(text);
    chat.setQuickReplies([]);
    chat.setBusy(true);
    try {
      const res = await fetch("/api/review/relate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ person_id: p.id, text }),
      });
      if (!res.ok) {
        chat.addAssistant("Sorry — I couldn't work out the exact relationship from that. Try one of the terms, or say it another way?");
        chat.setQuickReplies(optionsFor(p.relation).map((term) => ({ label: term, onClick: () => confirmWith(p, term) })));
        return;
      }
      const body = await res.json();
      const relation = body.note ? `${body.term} (${body.note})` : body.term;
      chat.addAssistant(`So she's your ${relation}. Confirming that.`);
      await confirmWith(p, relation);
    } catch (error) {
      console.error("import review: relation resolution failed", error);
      chat.addAssistant("Sorry — the assistant couldn't be reached. Try one of the terms instead?");
      chat.setQuickReplies(optionsFor(p.relation).map((term) => ({ label: term, onClick: () => confirmWith(p, term) })));
    } finally {
      chat.setBusy(false);
    }
  };

  const pending = proposedPeople(state);
  chat.addAssistant(`Let's finish the document import — ${pending.length} ${pending.length === 1 ? "person" : "people"} are still waiting to be confirmed.`);
  chat.onSend(resolveRelation);
  askFamily(pending[0]);
  return wrap;
}

/** Confirm: the person becomes family (status drops; confirmed records omit
 *  it) with the SPECIFIC kinship the review settled on. The server
 *  supersedes the archive, republishes, and returns the updated person —
 *  merge it; the chat advances without a re-render. Returns whether it
 *  saved. */
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
    return true;
  } catch (error) {
    console.error("import review: confirm failed", error);
    return false;
  }
}

/** Dismiss: dropped = gone (the proposed/confirmed seam). The person and
 *  their relationships leave the archive. */
async function dismissPerson(state, person) {
  try {
    const res = await fetch("/api/people/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: person.id }),
    });
    if (!res.ok) return false;
    state.people = state.people.filter((p) => p.id !== person.id);
    state.relationships = (state.relationships ?? []).filter((r) => r.a !== person.id && r.b !== person.id);
    if (proposedPeople(state).length === 0) {
      state.imports = (state.imports ?? []).map((s) => (s.status === "pending" ? { ...s, status: "reviewed" } : s));
    }
    return true;
  } catch (error) {
    console.error("import review: dismiss failed", error);
    return false;
  }
}
