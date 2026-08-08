/** Contributions — the "Your memories" blocks and the capture sheet.
 *  Read side: attributed story items listed on every entity page. Capture
 *  side: a chat with the assistant (app/chat.js, docs/CHAT-UX.md) — who's
 *  telling (autocompleted over the cast), the story, "anything else?" until
 *  the narrator says done, the AI's questions with quick-reply buttons (dates
 *  answered in the narrator's own words, interpreted by the model), then a
 *  review with editable proposed links —
 *  talking to the household capture server (/api/assess, /api/save). The
 *  deployed static site has no API — the affordance degrades to a note
 *  (docs/CONTRIBUTIONS.md).
 */

import { el } from "./ui.js";
import { dateLabel } from "./date.js";
import { autocomplete, chatBox } from "./chat.js";
import { me } from "./data.js";
import { signInSheet } from "./signin.js";

/** One story card: title link, attributed meta, and a preview snippet — the
 *  full account is on the story's own page (docs/CONTRIBUTIONS.md). */
export function storyCard(state, story) {
  const by = state.people.find((p) => p.id === story.told_by);
  // the events date must never read as the telling date — say both
  const told = story.recorded ? dateLabel({ date: story.recorded, date_precision: "exact" }) : null;
  const meta = [
    by ? `Told by ${by.name}` : null,
    story.status === "draft" ? "Draft" : null, // only the drafts surface lists these
    dateLabel(story),
    told ? `told ${told}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return el("div", { class: "response-card" }, [
    el("a", { class: "response-title", href: `#/item/${story.id}` }, story.title),
    meta ? el("div", { class: "card-meta" }, meta) : null,
    story.story ? el("p", { class: "response-quote" }, `“${preview(story.story)}”`) : null,
  ]);
}

/** The card shows a preview; the story page has the rest. Cut at a word
 *  boundary, never mid-word, and only when there is something to cut. */
function preview(text, limit = 140) {
  if (text.length <= limit) return text;
  const cut = text.slice(0, limit);
  const space = cut.lastIndexOf(" ");
  return `${cut.slice(0, space > 60 ? space : limit).trimEnd()}…`;
}

/** The memories block: title, attributed stories, and the affordance. */
/** The capture affordance — the one way a story is started from an entity
 *  page: the server check first, then the sheet. */
export function captureButton(state, anchor, label) {
  let note = null;
  const button = el(
    "button",
    {
      class: "btn",
      onclick: async () => {
        if (note) return;
        if (!(await serverReachable())) {
          // two-tier (docs/coding-standards.md): a plain line for the visitor,
          // the cause in the log — the capture server is not running
          console.warn("memories: capture server not reachable — showing the note");
          note = notReachableNote();
          button.after(note);
          note.scrollIntoView?.({ behavior: "smooth", block: "center" });
          return;
        }
        openSheet(state, anchor);
      },
    },
    label,
  );
  return button;
}

export function memoriesSection(state, { title, stories, buttonLabel, anchor, exclude = [] }) {
  // Render-once rule (2026-08-06): an item appears once per page — a story
  // already shown in the page's other lists is never re-shown in the
  // memories block. Pages pass the ids they have already rendered.
  const already = new Set(exclude);
  const shown = stories.filter((s) => !already.has(s.id));
  const section = el("section", { class: "block" }, [el("h3", { class: "block-title" }, title)]);
  section.append(
    shown.length
      ? el(
          "div",
          { class: "response-list" },
          shown.map((s) => storyCard(state, s)),
        )
      : el("p", { class: "empty" }, "No stories yet — the first one is yours to tell."),
  );
  section.append(captureButton(state, anchor, buttonLabel));
  return section;
}

function notReachableNote() {
  return el("div", { class: "memories-note", role: "status" }, [
    el("span", { class: "sv-label" }, "Can't reach the collection server"),
    el(
      "span",
      { class: "sv-note" },
      "Stories are gathered through the household server — this copy of the archive doesn't collect them. On the family's server, it may just be stopped — try again.",
    ),
  ]);
}

async function serverReachable() {
  try {
    const res = await fetch("/api/health", { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// The capture sheet — a chat with the assistant (docs/CHAT-UX.md)
// ---------------------------------------------------------------------------

/** Assemble the verbatim account: the story, each "anything else?" addition,
 *  and each answer under the question it answered. */
function assemble(entries) {
  const parts = [];
  for (const entry of entries) {
    if (entry.kind === "answer") parts.push(`Q: ${entry.question}\nA: ${entry.text}`);
    else parts.push(entry.text);
  }
  return parts.join("\n\n");
}

/** Case-insensitive name/alias match against the cast. */
function resolvePerson(name, people) {
  const wanted = name.trim().toLowerCase();
  return people.find((p) => [p.name, ...(p.aliases ?? [])].some((n) => String(n).toLowerCase() === wanted));
}

function openSheet(state, anchor, resume = null) {
  if (document.querySelector(".sheet-overlay")) return; // one capture at a time
  const session = {
    anchor,
    who: "",
    entries: [], // {kind: 'initial'|'add'|'answer', text, question?}
    title: "",
    extractions: [],
    facts: [], // structured dates from the assessment and the date picker
    questions: [],
    questionIndex: 0,
    saved: false,
    savedId: null,
    draftId: null, // the draft's id — auto-saves supersede it in place
    saving: false, // one draft fetch at a time; changes coalesce into the next
    stage: "who", // who | story | questions | review — where the flow was
    ...resume,
  };

  // -- abandon: get rid of the draft (user, 2026-08-03). Two taps — the
  //    first asks, the second confirms. The draft is tombstoned on the
  //    server (append-only: the files stay, it stops existing) and never
  //    re-saved by close.
  let abandoning = false;
  let abandonTimer = null;
  const abandonBtn = el(
    "button",
    {
      class: "btn btn-danger head-end",
      onclick: async () => {
        if (!session.entries.length) {
          close();
          return;
        } // nothing told — nothing to delete
        if (!abandoning) {
          abandoning = true;
          abandonBtn.textContent = "Abandon — really?";
          abandonTimer = setTimeout(() => {
            abandoning = false;
            abandonBtn.textContent = "Abandon";
          }, 4000);
          return;
        }
        clearTimeout(abandonTimer);
        session.saved = true; // the draft is going away — no re-save may resurrect it
        // a draft save may still be landing — wait for it, then delete by the
        // resolved id; an abandon never orphans a draft the narrator thought
        // they'd discarded (reviewer, 2026-08-03)
        if (session.savePromise) await session.savePromise.catch(() => {});
        if (session.draftId) {
          fetch("/api/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: session.draftId, reason: "abandoned by the narrator" }),
            keepalive: true,
          }).catch(() => {});
          state.byId.delete(session.draftId);
          state.items = state.items.filter((it) => it.id !== session.draftId);
        }
        close();
        window.dispatchEvent(new Event("hashchange")); // the drafts block re-renders
      },
    },
    "Abandon",
  );

  const overlay = el("div", { class: "sheet-overlay" });
  const sheet = el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": "Add a story" });
  const head = el("div", { class: "sheet-head" }, [
    el("button", { class: "btn", "aria-label": "Close", onclick: close }, "‹"),
    el("div", { class: "sheet-title" }, `A story about ${anchor.name ?? "the archive"}`),
    abandonBtn,
  ]);
  const body = el("div", { class: "sheet-body" });
  sheet.append(head, body);
  overlay.append(sheet);
  document.body.append(overlay);

  const chat = chatBox();
  body.append(chat.node);
  const show = (node) => {
    body.replaceChildren(node);
  };

  // -- the draft auto-save: the transcript lands on the server within a
  //    moment of any change, superseding in place — a distraction or a
  //    reboot loses at most the last few words (user, 2026-08-03) --------
  let draftTimer = null;
  const touch = () => {
    if (session.saved) return;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => saveDraft(session, state), 1500);
  };

  // a reboot or a closed tab must not eat an in-progress account — declared
  // before the resume branch so close() can always remove it
  const onUnload = () => {
    clearTimeout(draftTimer);
    if (!session.saved && !session.finalizing && session.entries.length > 0) saveDraft(session, state);
  };
  window.addEventListener("beforeunload", onUnload);

  function close() {
    window.removeEventListener("beforeunload", onUnload);
    clearTimeout(draftTimer);
    clearTimeout(abandonTimer);
    // nothing told is lost (§19.4): an abandoned session still saves a draft
    if (!session.saved && session.entries.length > 0) saveDraft(session, state);
    overlay.remove();
  }

  // -- who: the narrator IS the signed-in identity (2026-08-06, user:
  //    google auth — the localStorage name claim is gone). Signed in: the
  //    story stage starts under their name. Not signed in: the capture API
  //    requires the session, so the flow asks them to sign in first.
  const signedIn = me(state);
  const storyInput = () => el("textarea", { class: "field", rows: 1, placeholder: "Tell it however it comes…" });
  const moreHandler = (more) => {
    session.entries.push({ kind: "add", text: more });
    chat.addUser(more);
    chat.addAssistant("Anything else?");
    touch();
  };
  const askStory = () => {
    chat.swapInput(storyInput());
    chat.addAssistant(`Thanks, ${session.who}. What do you remember about ${anchor.name ?? "this"}?`);
    chat.onSend((story) => {
      session.entries.push({ kind: "initial", text: story });
      chat.addUser(story);
      chat.addAssistant("Anything else? — nothing is too small, and you can keep going as long as you like.");
      chat.setQuickReplies([{ label: "That's everything", primary: true, onClick: assess }]);
      chat.onSend(moreHandler);
      touch();
    });
  };
  const enterStory = () => {
    session.stage = "story";
    touch();
    if (session.entries.length === 0) {
      askStory();
    } else {
      chat.swapInput(storyInput()); // the story is already told
      chat.onSend(moreHandler);
    }
  };
  if (signedIn) {
    session.who = signedIn.name;
    session.who_id = signedIn.person ?? null;
    chat.setSelection({ label: signedIn.name }); // the identity, not a claim
    // a resume rebuilds the prompt from the transcript below — the fresh
    // flow's prompt would duplicate it (review, 2026-08-07)
    if (!resume) {
      chat.addAssistant("Signed in as you — what do you remember?");
      enterStory();
    }
  } else {
    chat.addAssistant("Sign in to tell your story — it will be saved under your name.");
    chat.setQuickReplies([
      {
        label: "Sign in with Google",
        primary: true,
        onClick: signInSheet,
      },
    ]);
  }

  // -- resume: reconstruct the chat from the stored transcript (user,
  //    2026-08-03 — a distraction or a reboot must never lose more than the
  //    last few words). The stored messages render as the transcript; the
  //    flow is wired live so it continues exactly where the narrator left.
  if (resume) {
    const stage = resume.stage ?? "review"; // legacy drafts (no chat) → review
    const entries = session.entries ?? [];
    const answers = entries.filter((e) => e.kind === "answer");
    const storyEntries = entries.filter((e) => e.kind !== "answer");
    if (stage !== "who" && session.who) {
      enterStory(); // the identity is the session — never a re-claim
      askStory(); // the story prompt + the story onSend
      storyEntries.forEach((e, i) => {
        if (i > 0) chat.addAssistant("Anything else?");
        chat.addUser(e.text);
      });
      if (storyEntries.length) {
        // the live state after the story: the keep-going prompt + the chip
        chat.addAssistant("Anything else? — nothing is too small, and you can keep going as long as you like.");
        chat.setQuickReplies([{ label: "That's everything", primary: true, onClick: assess }]);
      }
      chat.onSend(moreHandler); // the live input adds to the story
    }
    const questions = session.questions ?? [];
    if (stage === "questions" || stage === "review") {
      const upto = Math.min(session.questionIndex ?? answers.length, questions.length);
      for (let i = 0; i < Math.min(answers.length, upto); i++) {
        if (questions[i]) chat.addAssistant(questions[i].text, `The Loft · question ${i + 1} of ${questions.length}`);
        chat.addUser(answers[i].text);
      }
      for (let i = answers.length; i < upto; i++) {
        // questions skipped, not answered
        if (questions[i]) chat.addAssistant(questions[i].text, `The Loft · question ${i + 1} of ${questions.length}`);
      }
      if (upto < questions.length) {
        session.questionIndex = upto;
        askQuestion(upto);
      }
    }
    if (stage === "review") {
      renderReview();
      return;
    }
    return;
  }

  // -- assess: the assistant reads, everything is disabled while busy --------
  async function assess() {
    chat.setBusy(true, "Reading your story…");
    let assessment = null;
    try {
      const res = await fetch("/api/assess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ anchor, who: session.who, account: assemble(session.entries) }),
      });
      assessment = res.ok ? await res.json() : null;
    } catch (error) {
      console.error("memories: assess failed", error);
    }
    chat.setBusy(false);
    if (assessment?.ok) {
      session.title = assessment.title;
      session.extractions = assessment.extractions ?? [];
      session.facts = assessment.facts ?? [];
      session.questions = assessment.questions ?? [];
    } else {
      // the AI is unavailable — the story can still be saved without links,
      // and the narrator is told why the review is empty (reviewer, 2026-08-03)
      console.warn("memories: assessment unavailable — saving without links");
      session.assessNote =
        "The reader couldn't read your story just now — it will be saved as you told it, without any links. You can try again another time.";
      session.questions = [];
      session.extractions = [];
      session.facts = [];
    }
    if (session.questions.length) {
      session.questionIndex = 0;
      session.stage = "questions";
      touch();
      askQuestion(0);
    } else {
      renderReview();
    }
  }

  // -- questions: quick replies, dates in the narrator's own words, and the
  //    multi-select people flow ("who was there" — pick any number) --------
  function askQuestion(index) {
    session.questionIndex = index; // the live question — what the transcript records
    const q = session.questions[index];
    const meta = `The Loft · question ${index + 1} of ${session.questions.length}`;
    const buttons = [];
    if (q.type === "people") {
      askPeople(q, meta);
      return;
    }
    chat.swapInput(storyInput()); // a previous people question swapped it away
    for (const suggestion of q.suggestions ?? []) {
      buttons.push({ label: suggestion, onClick: () => answer(suggestion) });
    }
    if (q.skippable !== false) {
      buttons.push({ label: "Skip", onClick: nextQuestion });
    }
    buttons.push({ label: "I'd rather not say", onClick: () => answer("I'd rather not say") });
    chat.addAssistant(q.text, meta);
    chat.setQuickReplies(buttons); // chips attach to the question, above the input
    chat.onSend((value) => answer(value));
  }

  function askPeople(q, meta) {
    // several people: each picked name becomes a removable pill, the input
    // autocompletes over the cast, and a typed name is always an option
    // (a resumed draft restores the already-picked names from the transcript)
    session.personPicks = (session.extractions ?? [])
      .filter((ex) => ex.kind === "person" && ex.reason === "the narrator named them")
      .map((ex) => ex.name);
    const peopleAc = autocomplete({
      suggestions: state.people.flatMap((p) => [p.name, ...(p.aliases ?? [])]).filter(Boolean),
      placeholder: "Anyone else — type a name…",
    });
    const renderPills = () => {
      if (!session.personPicks.length) {
        chat.clearSelection();
        return;
      }
      chat.setSelection(
        session.personPicks.map((name) => ({
          label: name,
          onRemove: () => {
            session.personPicks = session.personPicks.filter((n) => n !== name);
            // the proposed link goes with the pill — the review must never
            // offer a person the narrator removed (reviewer, 2026-08-03)
            session.extractions = session.extractions.filter(
              (ex) => !(ex.kind === "person" && ex.reason === "the narrator named them" && ex.name === name),
            );
            renderPills();
          },
        })),
      );
    };
    renderPills();
    const pick = (name) => {
      const clean = String(name).trim();
      if (!clean || session.personPicks.includes(clean)) return;
      session.personPicks.push(clean);
      session.extractions.push({
        kind: "person",
        name: clean,
        match: resolvePerson(clean, state.people)?.id ?? null, // a cast member links, never re-mints
        bucket: "proposed",
        on: true,
        reason: "the narrator named them",
      });
      chat.addUser(clean);
      renderPills();
      peopleAc.input.value = "";
      touch();
    };
    const finish = () => {
      const text = session.personPicks.length ? session.personPicks.join(", ") : "nobody";
      session.entries.push({ kind: "answer", question: q.text, text });
      nextQuestion();
      touch();
    };
    chat.swapInput(peopleAc);
    chat.addAssistant(q.text, meta);
    chat.addAssistant(
      "Pick any number — tap a suggestion or type a name. When everyone's in, tap \"That's everyone\".",
    );
    chat.setQuickReplies(
      [
        ...(q.suggestions ?? []).map((s) => ({ label: s, onClick: () => pick(s) })),
        { label: "That's everyone", primary: true, onClick: finish },
        { label: "I'd rather not say", onClick: () => answer("I'd rather not say") },
        { label: "Skip", onClick: nextQuestion },
      ],
      { multi: true },
    );
    chat.onSend((value) => pick(value));
  }

  function answer(text) {
    const q = session.questions[session.questionIndex];
    session.entries.push({ kind: "answer", question: q.text, text });
    if (q.type === "date") {
      // the narrator's own answer is their assertion — confirmed. The value
      // is pending (null): the server asks the model to assert it and the
      // library validates; an unparseable answer stays null for a person's
      // word (docs/coding-standards.md: no hand-rolled date parsers).
      session.facts.push({
        kind: q.date_kind === "dob" ? "dob" : "event_date",
        entity: null,
        text,
        value: null,
        precision: null,
        status: "confirmed",
      });
    }
    chat.addUser(text);
    nextQuestion();
    touch();
  }

  function nextQuestion() {
    const next = session.questionIndex + 1;
    if (next < session.questions.length) {
      session.questionIndex = next;
      askQuestion(next);
    } else {
      renderReview();
    }
  }

  // -- review: what happens is stated plainly, links are obvious toggles -----
  function renderReview() {
    session.stage = "review";
    touch();
    const note = session.assessNote ? el("div", { class: "memories-note" }, session.assessNote) : null;
    const title = el("input", {
      class: "field",
      value: session.title || `A story about ${anchor.name ?? "the archive"}`,
    });
    const text = el("textarea", { class: "field field-textarea" }, []);
    text.value = assemble(session.entries);

    // each proposed link is a labelled checkbox — the state is obvious
    const toggles = el("div", { class: "link-toggles" });
    const renderToggles = () => {
      toggles.replaceChildren();
      for (const ex of session.extractions) {
        const on = ex.on !== false;
        let label;
        if (ex.kind === "item" && !ex.match) label = `${ex.name} — mentioned artifact, not in the archive yet`;
        else if (!ex.match) label = `${ex.name} — new ${ex.kind}, not in the archive yet`;
        else label = ex.name;
        toggles.append(
          el("label", { class: `link-toggle${on ? "" : " off"}` }, [
            el("input", {
              type: "checkbox",
              checked: on,
              onclick: () => {
                ex.on = on ? false : true;
                renderToggles();
              },
            }),
            el("span", {}, label),
          ]),
        );
      }
    };
    const addKind = el("select", { class: "field field-sm" }, [
      el("option", { value: "person" }, "person"),
      el("option", { value: "place" }, "place"),
    ]);
    const addName = el("input", { class: "field", placeholder: "Name…" });
    const addButton = el(
      "button",
      {
        class: "btn btn-primary",
        onclick: () => {
          const name = addName.value.trim();
          if (!name) return;
          const matched = addKind.value === "person" ? (resolvePerson(name, state.people)?.id ?? null) : null;
          session.extractions.push({
            kind: addKind.value,
            name,
            match: matched, // a cast member links, never re-mints (reviewer, 2026-08-03)
            bucket: "proposed",
            on: true,
            reason: "added by the narrator",
          });
          addName.value = "";
          renderToggles();
        },
      },
      "Add",
    );
    renderToggles();

    const form = el("div", { class: "sheet-form" }, [
      note,
      el("label", { class: "sheet-label" }, "Title"),
      title,
      el("label", { class: "sheet-label" }, "Your story — edit or redact anything before saving"),
      text,
      el(
        "div",
        { class: "sheet-label" },
        "These connections were picked out of your story — tick to keep, untick to leave out.",
      ),
      toggles,
      el("div", { class: "sheet-label" }, "Add a person or place the story is about"),
      el("div", { class: "add-link" }, [addKind, addName, addButton]),
      // the flow-ending action is last — everything else is an input
      el("div", { class: "sheet-progress" }, "Save puts the verified story into the archive."),
      el(
        "button",
        {
          class: "btn btn-primary sheet-primary",
          onclick: async () => {
            const saveBtn = form.querySelector(".sheet-primary"); // the Save button itself, never the Add row's
            saveBtn.disabled = true;
            clearTimeout(draftTimer);
            await save(
              session,
              state,
              {
                anchor,
                who: session.who,
                id: session.draftId ?? undefined, // an auto-saved draft becomes catalogued in place
                title: title.value.trim() || session.title,
                account: text.value,
                extractions: session.extractions.filter((ex) => ex.on !== false),
                facts: session.facts,
                chat: chatPayload(session),
                status: "catalogued", // verified in this review — the AI's guesses were checked here
              },
              () => renderSaved(),
            );
            // a failed save re-enables the button — the narrator's review
            // edits must be retryable, never stranded (reviewer, 2026-08-03)
            if (!session.saved) saveBtn.disabled = false;
          },
        },
        "Save story",
      ),
    ]);
    show(form);
  }

  function renderSaved() {
    show(
      el("div", { class: "sheet-form" }, [
        el("p", { class: "story" }, "Saved — it's in the archive."),
        el(
          "button",
          {
            class: "btn btn-primary",
            onclick: () => {
              overlay.remove();
              location.hash = `#/item/${session.savedId}`;
            },
          },
          "View it in the archive",
        ),
      ]),
    );
  }
}

/** The one way a saved story lands in the in-memory state: id-replacing
 *  upsert. A completed draft supersedes its own entry — a stale draft card
 *  must never linger until a reload (user, 2026-08-03). */
const mergeStory = (state, story) => {
  state.byId.set(story.id, story);
  const at = state.items.findIndex((it) => it.id === story.id);
  if (at >= 0) state.items[at] = story;
  else state.items.push(story);
};

/** Id-replacing merges for the records a save brings back — a resumed
 *  draft's already-merged person must never land twice (reviewer,
 *  2026-08-03). */
const mergeById = (list, records) => {
  for (const record of records) {
    const at = list.findIndex((x) => x.id === record.id);
    if (at >= 0) list[at] = record;
    else list.push(record);
  }
};

/** The structured transcript behind a draft — who, every message, the
 *  assessment, and where the flow was — so the chat can be reconstructed
 *  later (docs/CHAT-UX.md, user 2026-08-03). */
const chatPayload = (session) => ({
  anchor: session.anchor, // the page the narrator started from (reviewer, 2026-08-03)
  who: session.who,
  stage: session.stage,
  entries: session.entries,
  questions: session.questions,
  questionIndex: session.questionIndex,
  facts: session.facts,
  extractions: session.extractions,
});

/** POST the draft; on success merge the story and any proposed records into
 *  the in-memory state so navigation works without a reload. */
async function save(session, state, payload, onDone) {
  session.finalizing = true; // a tab close mid-save must not fire a draft save (reviewer, 2026-08-03)
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true, // an unload-initiated draft save must not be cancelled
    });
    if (!res.ok) throw new Error(`save failed: ${res.status}`);
    const body = await res.json();
    session.saved = true;
    session.savedId = body.id;
    mergeStory(state, body.story);
    mergeById(state.people, body.people ?? []);
    mergeById(state.places, body.places ?? []);
    onDone();
  } catch (error) {
    session.finalizing = false; // the failure is retryable
    console.error("memories: save failed", error);
    // two-tier: tell the visitor plainly, keep the form open to retry
    document
      .querySelector(".sheet-form")
      ?.append(el("div", { class: "memories-note" }, "Couldn't save — the server didn't accept it. Try again."));
  }
}

/** The draft save: the whole transcript lands on the server within a moment
 *  of any change, superseding the same story id in place (append-only — the
 *  archive keeps every version, the newest wins). Never marks the session
 *  saved: the final catalogued save does that. At most one fetch at a time;
 *  changes during a fetch coalesce into the next (user, 2026-08-03 — a
 *  reboot or a distraction loses at most the last few words). */
async function saveDraft(session, state) {
  // finalizing: the catalogued save is in flight — a draft save would race it
  // (and could supersede the finished story); the guard lives here so every
  // caller — close, unload, the debounce — honours it (reviewer, 2026-08-03).
  // A skip while saving re-queues itself: words typed mid-save must not wait
  // for the next change (reviewer, 2026-08-03).
  if (session.saved || session.finalizing || !session.entries.length) return;
  if (session.saving) {
    session.resavePending = true;
    return;
  }
  session.saving = true;
  // the in-flight promise — abandon awaits it so a draft that is landing
  // still gets deleted, never orphaned (reviewer, 2026-08-03)
  const run = (async () => {
    try {
      const res = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          anchor: session.anchor,
          id: session.draftId ?? undefined, // the first save mints; the rest supersede
          who: session.who || "Guest",
          title: session.title || "A story (unfinished)",
          account: assemble(session.entries),
          extractions: (session.extractions ?? []).filter((ex) => ex.on !== false),
          facts: session.facts ?? [],
          chat: chatPayload(session),
          status: "draft", // abandoned before the review — the AI's guesses stay unverified
        }),
        keepalive: true, // an unload-initiated draft save must not be cancelled
      });
      if (!res.ok) throw new Error(`draft save failed: ${res.status}`);
      const body = await res.json();
      session.draftId = body.id;
      // merge the draft into the in-memory state so the drafts surface and
      // navigation work without a reload — archival views filter it out. A
      // first-time narrator's minted person record must arrive too, or they
      // can never see their own draft (reviewer, 2026-08-03).
      mergeStory(state, body.story);
      for (const person of body.people ?? []) state.people.push(person);
      for (const place of body.places ?? []) state.places.push(place);
    } catch (error) {
      // two-tier: the words stay in the sheet; the next change retries
      console.warn("memories: draft save failed — the sheet keeps the words", error);
    } finally {
      session.saving = false;
    }
  })();
  session.savePromise = run;
  await run;
  // a change arrived while this save was in flight — go again so the newest
  // words land without waiting for the next touch (reviewer, 2026-08-03)
  if (session.resavePending && !session.saved && !session.finalizing) {
    session.resavePending = false;
    await saveDraft(session, state);
  }
}

/** The owner continues an unfinished draft: the sheet opens at the review,
 *  pre-filled from the sidecar — verify the links, edit the account, save it
 *  catalogued (user, 2026-08-03: a draft is for the person who claimed it). */
export function openDraft(state, draft) {
  const signedIn = me(state);
  const narrator = state.people.find((p) => p.id === draft.told_by);
  const who = signedIn?.name ?? narrator?.name ?? "Guest";
  const chat = draft.chat ?? {};
  // legacy drafts (no stored transcript) resume at the review with the
  // account as one entry — the old behaviour
  const refs = (list, kind) =>
    (list ?? []).map((r) => {
      const name =
        kind === "person"
          ? state.people.find((p) => p.id === r.id)?.name
          : kind === "place"
            ? state.places.find((p) => p.id === r.id)?.name
            : kind === "theme"
              ? state.themes.find((t) => t.id === r.id)?.title
              : (state.byId.get(r.id)?.title ?? r.id);
      return { kind, name: name ?? r.id, match: r.id, bucket: "proposed", on: true, reason: "already linked" };
    });
  openSheet(state, chat.anchor ?? { kind: "item", id: draft.comment_on ?? null, name: draft.title }, {
    draftId: draft.id, // abandon supersedes the same draft — never a copy
    who: chat.who ?? who,
    title: draft.title,
    entries: chat.entries ?? [{ kind: "initial", text: draft.story }],
    facts: chat.facts ?? draft.facts ?? [],
    extractions: chat.extractions ?? [
      ...refs(draft.people, "person"),
      ...refs(draft.places, "place"),
      ...refs(draft.themes, "theme"),
      ...refs(draft.items, "item"),
    ],
    questions: chat.questions ?? [],
    questionIndex: chat.questionIndex ?? 0,
    stage: chat.stage ?? "review",
  });
}
