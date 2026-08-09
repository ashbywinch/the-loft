/** The import review (user, 2026-08-07) — the review IS the chat (user,
 *  2026-08-08): opening the session's review starts the conversation about
 *  the unfinished doc import and walks through the pending links one at a
 *  time. Each link's EXACT claim is named — "the import proposes Quentin
 *  Whitlock is '…'" — and the reviewer picks a disposition with their
 *  confidence (2026-08-09): Definitely (attested), I think so (estimated),
 *  I don't know (keep pending), Definitely not / I think not (delete). The
 *  positives and the negatives each get a follow-up — "how do you know?"
 *  or "what do you remember?" — and the free text is checked against the
 *  exact claim AND the archive's attested facts: an off-topic answer is
 *  steered back, and a contradiction with the existing data (the
 *  the wrong-person-for-the-attested-event case) is surfaced and resolved before anything is
 *  confirmed. The decision vocabulary is NOT the status vocabulary —
 *  "confirm" is a status, never an action. The conversation is a record:
 *  every decision and exchange persists on the session's page (the API
 *  subset over the store), resumable from the last undecided link. */

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

/** One line of the review record: "Quentin Whitlock — confirmed (9 Aug
 *  2026)" or "— estimated, from Alex's recollection (9 Aug 2026): '…'." */
function decisionLine(name, d) {
  const when = d.when ? ` (${d.when})` : "";
  if (d.decision === "attested") return `${name} — confirmed${when}.`;
  if (d.decision === "estimated") {
    const basis = d.basis?.text ? `: '${d.basis.text}'` : "";
    return `${name} — estimated, from ${d.basis?.by ?? "the reviewer"}'s recollection${when}${basis}.`;
  }
  if (d.decision === "pending") return `${name} — kept as proposed${when}.`;
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
   *  first CONTENT sentence — a captured letter's routing header ("…
   *  — email, Wed … to Quentin Whitlock, opening 'Hi Pearl'") is metadata,
   *  never a quote (2026-08-09, user: the claim quoted the email's header). */
  const quoteFrom = (text) => {
    const sentences = text.split(/(?<=[.!?])\s+/).filter(Boolean);
    const headerish = /— (?:email|letter|note|document),|@|opening '|to [A-Z][a-z]+ [A-Z][a-z]+,/;
    const first = sentences.find((s) => s.length > 20 && !headerish.test(s));
    return first ? `${first.slice(0, 200).replace(/[.!?]$/, "")}.` : null;
  };

  const personSource = (p) => {
    const docs = (state.items ?? []).filter((it) => itemInvolves(it, p.id));
    const doc = [...docs].sort((a, b) => (a.date ?? "").localeCompare(b.date ?? ""))[0];
    if (!doc) return null;
    return { id: doc.id, title: doc.title, quote: quoteFrom((doc.transcription || "").trim()) };
  };

  const askDisposition = (p) => {
    person = p;
    pendingDecision = null;
    const source = personSource(p);
    chat.addAssistant(
      el("div", {}, [
        `Next: ${p.name}. `,
        source
          ? el("span", {}, [
              source.title ? `${source.title} mentions ${p.name}` : `A document mentions ${p.name}`,
              source.quote ? ` — it says, "${source.quote}"` : "",
              p.relation ? ` The notes describe ${p.name} as ${personable(p.relation)}.` : "",
              ` Does that fit what you remember? `,
              el("a", { class: "link", href: `#/item/${source.id}` }, "Open it →"),
            ])
          : p.relation
            ? `The notes describe ${p.name} as ${personable(p.relation)}. Does that fit what you remember?`
            : `The documents mention ${p.name}, but the notes don't say how. Does the name ring a bell?`,
      ]),
    );
    chat.setQuickReplies([
      { label: "Definitely", primary: true, onClick: () => askText(p, "How do you know?") },
      { label: "I think so", onClick: () => askText(p, "What do you remember that makes you think so?") },
      { label: "I don't know", onClick: () => askDontKnow(p) },
      { label: "Definitely not", onClick: () => askText(p, "What makes you say that?") },
      { label: "I think not", onClick: () => askText(p, "What makes you think not?") },
    ]);
  };

  /** The follow-up: the reviewer's own words are the recollection, never
   *  suggested (2026-08-09). */
  const askText = (p, question) => {
    person = p;
    pendingDecision = { p, statement: null, provenance: [] };
    chat.addAssistant(question);
    chat.swapInput(el("textarea", { class: "field", rows: 2, placeholder: "Say it as you'd tell a family member…" }));
  };

  const sendText = async (text) => {
    if (!person) return;
    const pending = pendingDecision;
    chat.addUser(text);
    chat.setQuickReplies([]);
    chat.setBusy(true);
    // the free text is checked against the exact claim AND the attested
    // facts — off-topic answers steer back, contradictions surface and
    // must be resolved before anything is confirmed (2026-08-09)
    const res = await checkText(state, session.id, person, text);
    if (!res) {
      chat.addAssistant("Sorry — the assistant couldn't be reached. Try again?");
      chat.setBusy(false);
      askDisposition(person);
      return;
    }
    if (res.relevant === "false") {
      chat.addAssistant(
        `That's about ${res.note ? `something else (${res.note})` : "something else"} — let's come back to ${person.name}: do you think the link's right?`,
      );
      chat.setBusy(false);
      pendingDecision = null;
      askDisposition(person);
      return;
    }
    if (res.contradiction?.found === "true") {
      chat.addAssistant(`That doesn't match the records — ${res.contradiction.detail}. Which is right?`);
      chat.setBusy(false);
      return; // the pending decision stays — the resolution is checked again
    }
    chat.setBusy(false);
    // the genealogist's response (2026-08-09, user): the digging said in
    // the documents' terms, the question, and the explicit confirmation —
    // the reviewer's recollection is never re-asked for, and every
    // resulting link is confirmed by hand before it is recorded
    if (res.findings?.length) {
      chat.addAssistant(
        el("div", {}, [
          "The documents show: ",
          ...res.findings.map((f, i) => {
            const text = typeof f === "string" ? f : f?.text ?? "";
            const id = typeof f === "object" ? f?.item_id : null;
            return el("span", {}, [
              i ? " " : "",
              text,
              id ? ` ${el("a", { class: "link", href: `#/item/${id}` }, "Open →")}` : "",
            ]);
          }),
        ]),
      );
    }
    if (res.question) {
      chat.addAssistant(res.question);
    }
    // the first statement is the recollection; later answers (the
    // question's answers, the provenance) accumulate beside it. The
    // disposition's NEGATIVE is captured from the first statement and kept
    // — a question-answer like "no, I don't remember" answers the
    // genealogist, it does not flip the disposition to removal (2026-08-09)
    const statement = pending?.statement ?? text;
    const provenance = pending?.provenance ? [...pending.provenance, text] : [];
    const negative = pending?.negative ?? (res.confidence === "definitely_not" || res.confidence === "think_not");
    pendingDecision = { p: person, statement, provenance, negative };
    chat.setQuickReplies(
      negative
        ? [
            { label: "Remove it", primary: true, onClick: () => recordDecision(person, "delete") },
            { label: "Leave it for now", onClick: () => keep(person) },
          ]
        : [
            { label: "Record as estimated", primary: true, onClick: () => recordDecision(person, "estimated") },
            { label: "Record as confirmed", onClick: () => recordDecision(person, "attested") },
            { label: "Leave it for now", onClick: () => keep(person) },
          ],
    );
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
    const ok = await decide(state, session.id, p, decision, basis);
    if (ok) {
      if (decision === "attested") {
        tally.attested += 1;
        chat.addAssistant(`Done — ${p.name} is recorded as confirmed.`);
      } else if (decision === "estimated") {
        tally.estimated += 1;
        chat.addAssistant(`Done — I've noted ${p.name} as your recollection: '${basisText}'.`);
      } else {
        tally.deleted += 1;
        chat.addAssistant(`Done — ${p.name} is not recorded after all.`);
      }
      advance();
    } else {
      chat.addAssistant("That didn't save — the server said no. Try again?");
      chat.setBusy(false);
      askDisposition(p);
    }
  };

  const askDontKnow = (p) => {
    person = p;
    pendingDecision = null;
    chat.addAssistant(
      `OK — ${p.name} stays as the import's guess (proposed) until we know more — or record them as estimated with what little you do know?`,
    );
    chat.setQuickReplies([
      { label: "Keep as proposed", primary: true, onClick: () => keep(p) },
      { label: "Mark estimated", onClick: () => askText(p, "What do you remember that makes you think so?") },
    ]);
  };

  const keep = async (p) => {
    chat.setBusy(true);
    const ok = await decide(state, session.id, p, "pending");
    if (ok) {
      tally.pending += 1;
      chat.addAssistant(`${p.name} stays as the import's guess for now — we can pick it up later.`);
      advance();
    } else {
      chat.addAssistant("That didn't save — the server said no. Try again?");
      chat.setBusy(false);
      askDisposition(p);
    }
  };

  /** One message per decision, then the next link — or the honest ending
   *  with a summary and a next action (2026-08-09). */
  const advance = () => {
    chat.setBusy(false); // success paths never cleared busy — the next
    // person's chips stayed hidden and the walkthrough dead-ended
    const pending = proposedPeople(state);
    if (!pending.length) {
      chat.addAssistant(
        `That's everyone — ${tally.attested ? `${tally.attested} confirmed, ` : ""}${tally.estimated ? `${tally.estimated} noted as your recollection, ` : ""}${tally.pending ? `${tally.pending} left as the import's guess, ` : ""}${tally.deleted ? `${tally.deleted} removed` : "and nothing removed"} — the rest were already in the tree, so nothing changed for them.`,
      );
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
  // (2026-08-09: the sessions' storage is attempt-separated)
  fetch("/api/review/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: session.id }),
  }).catch(() => {});
  chat.addAssistant(
    `Thanks for coming back — ${pending.length === 1 ? "there's 1 person" : `there are ${pending.length} people`} from the documents I'd like your eyes on${already ? `; everyone else is already in the tree` : ""}.`,
  );
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
    if (!res.ok) return false;
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
    return true;
  } catch (error) {
    console.error("import review: decide failed", error);
    return false;
  }
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
