/** The import review (user, 2026-08-07) — the review IS the chat (user,
 *  2026-08-08): opening the session's review starts the conversation about
 *  the unfinished doc import and walks through the pending links one at a
 *  time. Each link's EXACT claim is named — "Next: X. The document mentions
 *  X — it says, …" — and the reviewer picks a disposition with their
 *  confidence (2026-08-09): Definitely, I think so, I don't know,
 *  Definitely not / I think not. The confirmation chips are only offered
 *  AFTER the chat has gathered what they know, and only the options that
 *  obviously apply: Record as fact, Record as guess, Leave for later,
 *  Delete (2026-08-10, user: "don't suggest any of these until we've
 *  chatted about what they know and excluded any options that obviously
 *  don't apply" — the chips name the consequence, never the statuses:
 *  the family never meets proposed/estimated/confirmed). The positives and
 *  the negatives each get a follow-up — "how do you know?" or "what do you
 *  remember?" — and the free text is checked against the exact claim AND
 *  the archive's attested facts: an off-topic answer is steered back, and a
 *  contradiction with the existing data (the wrong-person-for-the-attested-
 *  event case) is surfaced and resolved before anything is confirmed. The
 *  decision vocabulary is NOT the status vocabulary — "confirm" is a
 *  status, never an action. The conversation is a record: every decision
 *  and exchange persists on the session's page (the API subset over the
 *  store), resumable from the last undecided link. */

import { el, header } from "../ui.js";
import { proposedPeople } from "../data.js";
import { chatBox } from "../chat.js";
import { itemInvolves } from "../connections.js";

export function render(main, ctx, state) {
  const session = (state.imports ?? []).find((s) => s.id === ctx.arg);
  if (!session) {
    main.append(header("The import", state), el("p", { class: "empty" }, "Not found."));
    return;
  }
  main.append(header(session.title, state));
  const pending = proposedPeople(state);
  // the transcript lives on the page of the artifact being reviewed — this
  // walk's decisions so far, named and dated (2026-08-09: the storage is
  // attempt-separated, so "the review so far" is the CURRENT walk's)
  const currentAttempt = session.attempts?.[session.attempts.length - 1];
  const decisions = currentAttempt?.decisions ?? [];
  if (decisions.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "The review so far"),
        ...decisions.map((d) => {
          const p = state.people.find((x) => x.id === d.person_id);
          return el("p", { class: "card-meta" }, decisionLine(p?.name ?? d.person_id, d));
        }),
      ]),
    );
  }
  if (!pending.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h2", { class: "block-title" }, "Everything is resolved"),
        el("p", { class: "memories-note" }, "Nothing is waiting — the import is done."),
      ]),
    );
    return;
  }
  main.append(
    el("section", { class: "block import-pending" }, [
      el("h2", { class: "block-title" }, `${pending.length} ${pending.length === 1 ? "link" : "links"} awaiting a decision`),
      reviewSession(state, session),
    ]),
  );
}

/** One line of the review record: "Quentin Whitlock — recorded as a fact
 *  (9 Aug 2026)" or "— recorded as a guess, from Alex's recollection
 *  (9 Aug 2026): '…'." — the family's words, never the statuses
 *  (2026-08-10, user). */
function decisionLine(name, d) {
  const when = d.when ? ` (${d.when})` : "";
  if (d.decision === "attested") return `${name} — recorded as a fact${when}.`;
  if (d.decision === "estimated") {
    const basis = d.basis?.text ? `: '${d.basis.text}'` : "";
    return `${name} — recorded as a guess, from ${d.basis?.by ?? "the reviewer"}'s recollection${when}${basis}.`;
  }
  if (d.decision === "pending") return `${name} — left for later${when}.`;
  return `${name} — removed${when}.`;
}

// -- the review conversation — one chat walks the whole session --------------

function reviewSession(state, session) {
  const chat = chatBox();
  const wrap = el("div", { class: "import-review" });
  wrap.append(chat.node);

  let person = null;
  let pendingDecision = null; // {p, decision} while the free text's being checked
  let tally = { attested: 0, estimated: 0, pending: 0, deleted: 0 };
  // the links decided during THIS walk — a kept link stays proposed in the
  // table, so the walk must not re-ask it (2026-08-10 review)
  const decidedIds = new Set();
  const reviewer = state.me?.name ?? "the reviewer";
  const today = new Date().toISOString().slice(0, 10);

  /** The claim, in the genealogist's voice (2026-08-09, user: the review
   *  must read like a hired researcher's DM, never a system quoting its
   *  records — the internal annotation "the user's recollection" is the
   *  app telling the family about itself). */
  const personable = (relation) =>
    relation
      .replace(/the user's recollection, \d{4}-\d{2}-\d{2}:?\s*/gi, "")
      .replace(/\(([^)]*)\)/g, " — $1")
      .replace(/— (— )+/g, "— ")
      .replace(/\s+/g, " ")
      .trim();

  /** The document that brought the person in — the earliest item that
   *  mentions them — with a DIRECT QUOTE from its transcription, so the
   *  family can see the document's own words versus the notes' summary
   *  (2026-08-09, user: "specify which document… make it very clear
   *  what's a direct quote and what's not… with a link"). The quote is the
   *  sentence that MENTIONS the person — the part that attests the fact —
   *  never the document's first sentence (2026-08-09, user: "extremely bad
   *  at identifying the relevant part of the document to quote when
   *  explaining the attestation of the fact in question"); a captured
   *  letter's routing header ("… — email, Wed … to Quentin Whitlock,
   *  opening 'Hi Pearl'") is metadata, never a quote. */
  const quoteFrom = (text, name) => {
    const sentences = text.split(/(?<=[.!?])\s+/).filter(Boolean);
    const headerish = /— (?:email|letter|note|document),|@|opening '|to [A-Z][a-z]+ [A-Z][a-z]+,/;
    const words = name.split(/\s+/);
    const mentions =
      sentences.find((s) => s.length > 20 && words.every((w) => s.includes(w)) && !headerish.test(s)) ??
      sentences.find((s) => s.length > 20 && s.includes(words[0]) && !headerish.test(s));
    const first = sentences.find((s) => s.length > 20 && !headerish.test(s));
    return mentions || first ? `${(mentions || first).slice(0, 200).replace(/[.!?]$/, "")}.` : null;
  };

  const personSource = (p) => {
    const docs = (state.items ?? []).filter((it) => itemInvolves(it, p.id));
    const doc = [...docs].sort((a, b) => (a.date ?? "").localeCompare(b.date ?? ""))[0];
    if (!doc) return null;
    // Rule L (2026-08-11 review): a draft transcription's sentence is
    // never presented as the document's own words — only verified text is
    // quoted as "it says"
    const quote = doc.transcription_status === "draft" ? null : quoteFrom((doc.transcription || "").trim(), p.name);
    return { id: doc.id, title: doc.title, quote };
  };

  const askDisposition = (p) => {
    person = p;
    pendingDecision = null;
    const source = personSource(p);
    const claimText = source
      ? `Next: ${p.name}. ${source.title ? `${source.title} mentions ${p.name}` : `A document mentions ${p.name}`}${source.quote ? ` — it says, "${source.quote}"` : ""}${p.relation ? ` The notes describe ${p.name} as ${personable(p.relation)}.` : ""} Does that fit what you remember?`
      : p.relation
        ? `Next: ${p.name}. The notes describe ${p.name} as ${personable(p.relation)}. Does that fit what you remember?`
        : `Next: ${p.name} — the documents mention them, but the notes don't say how. Does the name ring a bell?`;
    chat.addAssistant(
      source ? el("div", {}, [claimText + " ", el("a", { class: "link", href: `#/item/${source.id}` }, "Open it →")]) : claimText,
    );
    // the claim is part of the conversation the family saw — record it
    // once per attempt (2026-08-10 review: a re-render must not duplicate
    // the transcript)
    recordIfNew("assistant", claimText);
    chat.setQuickReplies([
      { label: "Definitely", primary: true, onClick: () => askText(p, "How do you know?", "positive") },
      { label: "I think so", onClick: () => askText(p, "What do you remember that makes you think so?", "positive") },
      { label: "I don't know", onClick: () => askDontKnow(p) },
      { label: "Definitely not", onClick: () => askText(p, "What makes you say that?", "negative") },
      { label: "I think not", onClick: () => askText(p, "What makes you think not?", "negative") },
    ]);
  };

  /** The follow-up: the reviewer's own words are the recollection, never
   *  suggested (2026-08-09). The disposition (positive / negative /
   *  dont_know) is captured from the initial chip and kept — a
   *  question-answer never flips a "Definitely not" into an offer to
   *  record the link as a fact (2026-08-10, user: the offered options must
   *  exclude what obviously doesn't apply). */
  const askText = (p, question, disposition = null) => {
    person = p;
    pendingDecision = { p, statement: null, provenance: [], disposition };
    chat.addAssistant(question);
    chat.setQuickReplies([]); // the question replaces the disposition chips (2026-08-10)
    recordIfNew("assistant", question); // the questions are part of what the family saw
    chat.swapInput(el("textarea", { class: "field", rows: 2, placeholder: "Say it as you'd tell a family member…" }));
  };

  /** "I don't know" is not a dead end and not a button-push — the
   *  genealogist first asks what they know, even a little; only then are
   *  the options offered (2026-08-10, user: "don't suggest any of these
   *  until we've chatted about what they know"). */
  const askDontKnow = (p) => askText(p, "What do you remember about them, even a little?", "dont_know");

  const sendText = async (text) => {
    if (!person) return;
    const pending = pendingDecision;
    chat.addUser(text);
    chat.setQuickReplies([]);
    chat.setBusy(true);
    // the opening and the claim must be recorded BEFORE this line — a fast
    // reviewer could type before the start fetch resolved, and the server
    // would order the user's line first (2026-08-11 review, R7)
    await started;
    // the free text is checked against the exact claim AND the attested
    // facts — off-topic answers steer back, contradictions surface and
    // must be resolved before anything is confirmed (2026-08-09)
    const res = await checkText(state, session.id, person, text);
    if (!res) {
      chat.addAssistant("Sorry — the assistant couldn't be reached. Try again?");
      recordIfNew("assistant", "Sorry — the assistant couldn't be reached. Try again?");
      chat.setBusy(false);
      askDisposition(person);
      return;
    }
    // the assistant's words are built by the server and shown verbatim —
    // the transcript records exactly what the family saw (2026-08-09: the
    // steer, the contradiction, the findings, and the question all arrive
    // as the server's rendered message; the model's internal note never
    // reaches the user)
    if (res.message) {
      chat.addAssistant(res.message);
    }
    if (res.relevant === "false") {
      chat.setBusy(false);
      pendingDecision = null;
      askDisposition(person);
      return;
    }
    if (res.contradiction?.found === "true") {
      chat.setBusy(false);
      // the contradiction is surfaced; the reviewer is never stuck re-
      // answering (2026-08-11 review, R4/R6): they can record their
      // standing disagreement as a guess (their words become the basis),
      // leave it for later, or delete — "Record as fact" is never offered,
      // because the evidence disputes the claim
      const LEAVE = { label: "Leave for later", onClick: () => keep(person) };
      const DELETE = { label: "Delete", onClick: () => recordDecision(person, "delete") };
      const GUESS = { label: "Record as a guess", primary: true, onClick: () => recordDecision(person, "estimated") };
      // the statement is kept for the guess's basis, but NO disposition is
      // captured — a reviewer who then resolves the contradiction flows
      // through the normal confidence-based chips (2026-08-11)
      pendingDecision = { p: person, statement: text, provenance: [], disposition: null };
      chat.setQuickReplies([GUESS, LEAVE, DELETE]);
      return; // the pending decision stays — the resolution is checked again
    }
    chat.setBusy(false);
    // the first statement is the recollection; later answers (the
    // question's answers, the provenance) accumulate beside it. The
    // disposition is captured from the initial chip and kept (2026-08-10)
    const statement = pending?.statement ?? text;
    const provenance = pending?.provenance ? [...pending.provenance, text] : [];
    const disposition = pending?.disposition ?? null;
    pendingDecision = { p: person, statement, provenance, disposition };
    // the confirmation chips name the CONSEQUENCE, in the family's words —
    // never the statuses (2026-08-10, user). Only the options that
    // obviously apply are offered: a negative answer never offers "Record
    // as fact", a "don't know" never offers fact or delete, a definite
    // answer never offers "Record as guess".
    const FACT = { label: "Record as fact", onClick: () => recordDecision(person, "attested") };
    const GUESS = { label: "Record as guess", onClick: () => recordDecision(person, "estimated") };
    const LEAVE = { label: "Leave for later", onClick: () => keep(person) };
    const DELETE = { label: "Delete", onClick: () => recordDecision(person, "delete") };
    const chipsFor = (confidence, disc) => {
      if (disc === "negative" || confidence === "definitely_not" || confidence === "think_not") {
        return [{ ...DELETE, primary: true }, LEAVE];
      }
      if (disc === "dont_know" || confidence === "dont_know") {
        return [{ ...LEAVE, primary: true }, GUESS];
      }
      switch (confidence) {
        case "definitely":
          return [{ ...FACT, primary: true }, LEAVE];
        case "think_so":
          return [{ ...GUESS, primary: true }, FACT, LEAVE];
        default: // unclear — nothing obviously excluded, but a positive start never offers delete
          return disc === "positive"
            ? [{ ...LEAVE, primary: true }, GUESS, FACT]
            : [{ ...LEAVE, primary: true }, GUESS, FACT, DELETE];
      }
    };
    chat.setQuickReplies(chipsFor(res.confidence, disposition));
  };

  /** The explicit confirmation (2026-08-09, user): the reviewer confirms
   *  the resulting link by hand — estimated or attested — with their own
   *  words as the basis and any provenance answers beside it. */
  const recordDecision = async (p, decision) => {
    const pending = pendingDecision ?? { p, statement: "", provenance: [] };
    chat.setBusy(true);
    const basisText = pending.statement || "the reviewer's recollection";
    const provenance = pending.provenance?.length ? pending.provenance.join(" ") : null;
    const basis =
      decision === "attested" || decision === "estimated"
        ? { text: basisText, by: reviewer, when: today, ...(provenance ? { note: provenance } : {}) }
        : null;
    const result = await decide(state, session.id, p, decision, basis);
    if (result) {
      if (decision === "attested") tally.attested += 1;
      else if (decision === "estimated") tally.estimated += 1;
      else tally.deleted += 1;
      decidedIds.add(p.id); // a kept person stays proposed — the walk must not re-ask them (2026-08-10 review)
      // the confirmation is the server's rendered words — shown verbatim,
      // recorded verbatim (2026-08-09)
      chat.addAssistant(result === true ? `Done — ${p.name} is recorded.` : result);
      advance();
    } else {
      chat.addAssistant("That didn't save — the server said no. Try again?");
      recordIfNew("assistant", "That didn't save — the server said no. Try again?");
      chat.setBusy(false);
      askDisposition(p);
    }
  };

  const keep = async (p) => {
    chat.setBusy(true);
    const ok = await decide(state, session.id, p, "pending");
    if (ok) {
      tally.pending += 1;
      decidedIds.add(p.id); // still proposed in the table — never re-ask this walk (2026-08-10 review)
      chat.addAssistant(`${p.name} stays out of the tree for now — we can pick it up later.`);
      advance();
    } else {
      chat.addAssistant("That didn't save — the server said no. Try again?");
      recordIfNew("assistant", "That didn't save — the server said no. Try again?");
      chat.setBusy(false);
      askDisposition(p);
    }
  };

  /** One message per decision, then the next link — or the honest ending
   *  with a summary and a next action (2026-08-09). The kept links are
   *  filtered out of the queue for THIS walk — they stay proposed in the
   *  table as the session's resume point (2026-08-10 review: the walk
   *  re-asked the same kept link forever). */
  const advance = () => {
    chat.setBusy(false); // success paths never cleared busy — the next
    // person's chips stayed hidden and the walkthrough dead-ended
    const pending = proposedPeople(state).filter((p) => !decidedIds.has(p.id));
    if (!pending.length) {
      const summary = `That's everyone — ${tally.attested ? `${tally.attested} recorded as facts, ` : ""}${tally.estimated ? `${tally.estimated} recorded as guesses, ` : ""}${tally.pending ? `${tally.pending} left for later, ` : ""}${tally.deleted ? `${tally.deleted} deleted` : "and nothing deleted"} — the rest were already in the tree, so nothing changed for them.`;
      chat.addAssistant(summary);
      recordIfNew("assistant", summary); // the ending is part of what the family saw (2026-08-11 review)
      chat.setQuickReplies([{ label: "See the family tree →", primary: true, onClick: () => location.assign("#/tree") }]);
      return;
    }
    askDisposition(pending[0]);
  };

  const pending = proposedPeople(state);
  const already = (state.people?.length ?? 0) - pending.length;
  // a resumed session continues from the last undecided link (the record's
  // resume point), never from the top
  const resumeId = session.current;
  const first = resumeId ? pending.find((p) => p.id === resumeId) ?? pending[0] : pending[0];
  // begin the walk — a fresh attempt only when the last one is finished
  // (2026-08-09: the sessions' storage is attempt-separated). The start
  // response carries the lines already recorded in the current attempt, so
  // a re-render records only what's new — the transcript never duplicates
  // the opening or a claim (2026-08-10 review). Every app-rendered line
  // waits for this before recording, so the check is never raced
  let seenLines = new Set();
  const started = fetch("/api/review/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: session.id }),
  })
    .then((r) => r.json())
    .then((body) => {
      if (Array.isArray(body?.messages)) seenLines = new Set(body.messages);
    })
    .catch(() => {});
  /** Record one of the app's own rendered lines exactly once per attempt
   *  (2026-08-10 review: "the persisted transcript then no longer equals
   *  what the family saw"). */
  const recordIfNew = (role, text) => {
    const record = () => {
      if (seenLines.has(text)) return;
      seenLines.add(text);
      recordMessage(session.id, role, text);
    };
    started.then(record, record);
  };
  const opening = `Thanks for coming back — ${pending.length === 1 ? "there's 1 person" : `there are ${pending.length} people`} from the documents I'd like your eyes on${already ? `; everyone else is already in the tree` : ""}.`;
  chat.addAssistant(opening);
  recordIfNew("assistant", opening);
  chat.onSend(sendText);
  askDisposition(first);
  return wrap;
}

/** One decision per proposed link — the four dispositions (2026-08-09).
 *  Returns whether it saved; the server's response person is merged (or
 *  dropped for a delete). */
async function decide(state, sessionId, person, decision, basis = null) {
  try {
    const res = await fetch("/api/review/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, person_id: person.id, decision, basis }),
    });
    if (!res.ok) return null;
    const body = await res.json();
    const updated = body.person;
    if (updated?.gone) {
      state.people = state.people.filter((p) => p.id !== person.id);
      state.relationships = (state.relationships ?? []).filter((r) => r.a !== person.id && r.b !== person.id);
    } else if (updated) {
      const idx = state.people.findIndex((p) => p.id === updated.id);
      if (idx >= 0) state.people[idx] = updated;
      else state.people.push(updated);
    }
    // the last pending link completes the session — the server agrees, but
    // the client's merged state must too, or the card lingers until a reload
    if (proposedPeople(state).length === 0) {
      state.imports = (state.imports ?? []).map((s) => (s.id === sessionId && s.status === "pending" ? { ...s, status: "reviewed" } : s));
    }
    // the confirmation's rendered words — shown verbatim, recorded verbatim
    return body.message ?? true;
  } catch (error) {
    console.error("import review: decide failed", error);
    return null;
  }
}

/** Record one of the app's own rendered lines (the claim, the opening) so
 *  the transcript is exactly what the family saw (2026-08-09). */
function recordMessage(sessionId, role, text) {
  fetch("/api/review/message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, role, text }),
  }).catch(() => {});
}

/** The free-text check — relevance + contradiction (off-topic answers
 *  steer back, contradictions surface). Returns the parsed body, or null
 *  when the server couldn't be reached. */
async function checkText(state, sessionId, person, text) {
  try {
    const res = await fetch("/api/review/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, person_id: person.id, text }),
    });
    if (!res.ok) return null;
    return res.json();
  } catch (error) {
    console.error("import review: text check failed", error);
    return null;
  }
}
