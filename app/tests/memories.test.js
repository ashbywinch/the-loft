import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { memoriesSection, openDraft, storyCard } from "../memories.js";

const STATE = {
  people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
  items: [],
  places: [],
  themes: [],
  byId: new Map(),
  me: { name: "Alex Hale", person: "p-alex" }, // the signed-in identity (2026-08-06)
};

const story = (overrides = {}) => ({
  id: "story-x",
  title: "A story",
  type: "story",
  date: "1963-05",
  date_precision: "month",
  recorded: "2026-08-03",
  story: "The curator: a verbatim account.",
  told_by: "p-alex",
  people: [],
  places: [],
  themes: [],
  ...overrides,
});

const ANCHOR = { kind: "theme", id: "t-the-boats", name: "The boats" };
const okJson = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const tick = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => {
  vi.useFakeTimers(); // never real timers — every test's independence is visible here (2026-08-05)
  localStorage.clear(); // no narrator or draft state leaks between tests
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new TypeError("no server"))),
  );
});

afterEach(async () => {
  // a leftover session must not leak its pending save into the next test's
  // fetch mock — close it the way the app does (the X clears the debounce
  // and the unload listener), then drain, then clean the DOM.
  document.querySelector('.sheet-overlay .btn[aria-label="Close"]')?.click();
  await vi.advanceTimersByTimeAsync(0);
  vi.useRealTimers(); // every test restores the real clock; the next beforeEach re-fakes it
  localStorage.clear();
  document.querySelector(".sheet-overlay")?.remove();
});

const chatInput = () => document.querySelector(".chat-bar .field");
const chipLabel = () => document.querySelector(".chat-selection .chip-label")?.textContent;
const sendBtn = () => document.querySelector(".chat-bar .btn-primary");
const action = (label) => [...document.querySelectorAll(".chat-quick .chip")].find((b) => b.textContent === label);
/** Setting .value programmatically does not fire the input event — the send
 *  button would stay disabled. Dispatch it, like a real keystroke. */
const setInput = (text) => {
  chatInput().value = text;
  chatInput().dispatchEvent(new Event("input"));
};

async function openSheetVia(state, anchor = ANCHOR) {
  const section = memoriesSection(state, { title: "T", stories: [], buttonLabel: "Add a memory", anchor });
  section.querySelector("button.btn").click();
  await tick();
  return document.querySelector(".sheet");
}

describe("storyCard", () => {
it("a required (non-skippable) question offers no Skip button", async () => {
  // the events-date question is required (2026-08-05: the flow must make
  // the narrator provide a date) — Skip must not be offered; the narrator's
  // right to demur stays ("I'd rather not say"). Fake timers and a clean
  // localStorage come from beforeEach — this test is independent by setup,
  // not by position.
  const fetchMock = vi.fn((url) => {
    if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
    if (url === "/api/assess")
      return Promise.resolve(
        okJson({
          ok: true,
          title: "T",
          extractions: [],
          facts: [],
          questions: [
            {
              text: "When did this happen?",
              why: "",
              skippable: false,
              suggestions: [],
              type: "date",
              date_kind: "event",
            },
          ],
        }),
      );
    if (url === "/api/save")
      return Promise.resolve(
        okJson({
          ok: true,
          id: "story-draft",
          story: { id: "story-draft", status: "draft" },
          people: [],
          places: [],
        }),
      ); // the close-save must succeed — a failed save re-queues its debounce
    return Promise.resolve(okJson({ ok: false }, 404));
  });
  vi.stubGlobal("fetch", fetchMock);
  const sheet = await openSheetVia({ ...STATE });
  setInput("Alex");
  sendBtn().click();
  await tick();
  setInput("We went to Marlock.");
  sendBtn().click();
  await tick();
  action("That's everything").click();
  await tick();
  await tick();
  expect(sheet.textContent).toContain("When did this happen?");
  const chips = [...sheet.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent);
  expect(chips).not.toContain("Skip");
  expect(chips).toContain("I'd rather not say");
  [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
  await tick();
});

  it("links to the story page and attributes narrator, events and told dates", () => {
    const card = storyCard(STATE, story());
    const link = card.querySelector("a.response-title");
    expect(link.getAttribute("href")).toBe("#/item/story-x");
    expect(link.textContent).toBe("A story");
    // the events date (May 1963) must never read as the telling date
    expect(card.querySelector(".card-meta").textContent).toBe("Told by Alex Hale · May 1963 · told 3 Aug 2026");
  });

  it("renders a preview snippet, not the whole account", () => {
    const long = story({ story: "One. ".repeat(200) });
    const card = storyCard(STATE, long);
    const quote = card.querySelector(".response-quote").textContent;
    expect(quote.length).toBeLessThan(160);
    expect(quote.endsWith("…”")).toBe(true); // ellipsis before the closing quote
  });

  it("shows the whole account when it fits", () => {
    const card = storyCard(STATE, story());
    expect(card.querySelector(".response-quote").textContent).toContain("a verbatim account");
    expect(card.querySelector(".response-quote").textContent.endsWith("…")).toBe(false);
  });

  it("omits the byline when told_by is unknown", () => {
    const card = storyCard(STATE, story({ told_by: "p-nobody" }));
    expect(card.querySelector(".card-meta").textContent).not.toContain("Told by");
  });
});

describe("memoriesSection", () => {
  it("lists attributed stories under the title", () => {
    const section = memoriesSection(STATE, {
      title: "Stories about Nora",
      stories: [story(), story({ id: "story-y", title: "Another" })],
      buttonLabel: "Add a memory",
      anchor: ANCHOR,
    });
    expect(section.querySelector(".block-title").textContent).toBe("Stories about Nora");
    expect(section.querySelectorAll(".response-card").length).toBe(2);
  });

  it("shows a first-story hint when there are none yet", () => {
    const section = memoriesSection(STATE, { title: "T", stories: [], buttonLabel: "B", anchor: ANCHOR });
    expect(section.querySelector(".empty").textContent).toContain("No stories yet");
    expect(section.querySelectorAll(".response-card").length).toBe(0);
  });

  it("shows the not-reachable note when the capture server is down, once", async () => {
    const section = memoriesSection(STATE, { title: "T", stories: [], buttonLabel: "Add a memory", anchor: ANCHOR });
    const btn = section.querySelector("button.btn");
    btn.click();
    await tick();
    expect(section.querySelector(".memories-note")).toBeTruthy();
    expect(section.textContent).toContain("Can't reach the collection server");
    btn.click();
    await tick();
    expect(section.querySelectorAll(".memories-note").length).toBe(1);
  });
});

describe("the capture chat", () => {
  it("signed out, the chat asks them to sign in — never for a name (2026-08-06)", async () => {
    vi.stubGlobal("fetch", flowFetch());
    const state = { ...STATE, me: null };
    const sheet = await openSheetVia(state);
    expect(sheet.textContent).toContain("Sign in to tell your story");
    expect(document.querySelector(".chat-bar .ac")).toBeNull(); // no name autocomplete, ever
    expect(sheet.textContent).toContain("Sign in with Google");
  });

  it("signed in, the flow opens straight on the story with the identity pill", async () => {
    vi.stubGlobal("fetch", flowFetch());
    const state = { ...STATE };
    const sheet = await openSheetVia(state);
    expect(sheet.textContent).not.toContain("new person");
    expect(sheet.textContent).toContain("What do you remember about The boats");
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
  });

  it("disables typing and sending while the assistant reads the story", async () => {
    let resolveAssess;
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/assess")
        return new Promise((resolve) => {
          resolveAssess = resolve;
        });
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-x",
            story: { id: "story-x", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const sheet = await openSheetVia({ ...STATE });
    setInput("We went to Marlock.");
    sendBtn().click();
    await tick();
    action("That's everything").click();
    await tick();
    // the assistant is reading: nothing can be typed or sent
    expect(sheet.textContent).toContain("Reading your story…");
    expect(sendBtn().disabled).toBe(true);
    expect(chatInput().disabled).toBe(true);
    resolveAssess(okJson({ ok: true, title: "T", extractions: [], facts: [], questions: [] }));
    await tick();
    await tick();
    // no questions -> the review form takes over; the busy state is over
    expect(document.querySelector(".sheet-form")).toBeTruthy();
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
  });

  const flowFetch = () =>
    vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/assess")
        return Promise.resolve(
          okJson({
            ok: true,
            title: "The trips",
            extractions: [{ kind: "place", name: "Marlock", match: "pl-marlock", bucket: "proposed", reason: "" }],
            facts: [{ kind: "event_date", text: "May 1963", value: "1963-05", precision: "month" }],
            questions: [
              {
                text: "When did this happen?",
                why: "",
                skippable: true,
                suggestions: [],
                type: "date",
                date_kind: "event",
              },
              { text: "Who was there?", why: "", skippable: true, suggestions: [] },
            ],
          }),
        );
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-x",
            story: { id: "story-x", type: "story", title: "The trips", story: "told", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });

  it("the identity pill is not a claim — no remove, the story continues (2026-08-06)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(okJson({ ok: true }, 200))),
    ); // the sheet checks /api/health on open
    const sheet = await openSheetVia(STATE);
    expect(chipLabel()).toBe("Alex Hale");
    expect(document.querySelector(".chat-selection .chip-remove")).toBeNull(); // signed-in: not removable
    setInput("We went to Marlock.");
    sendBtn().click();
    await tick();
    expect(sheet.textContent).toContain("Anything else?");
  });

  it("runs as a chat: who, story, unbounded anything-else, questions, review, save", async () => {
    const fetchMock = flowFetch();
    vi.stubGlobal("fetch", fetchMock);
    const state = { ...STATE };
    const sheet = await openSheetVia(state);

    // the narrator IS the session (2026-08-06, google auth) — the chat
    // opens on the story, with the identity as a fixed pill
    expect(sheet.textContent).not.toContain("Who's telling this?");
    expect(chipLabel()).toBe("Alex Hale");
    expect(document.querySelector(".chat-selection .chip-remove")).toBeNull(); // not a claim, not removable
    expect(sheet.textContent).toContain("What do you remember about The boats");

    // the story
    setInput("We went to Marlock.");
    sendBtn().click();
    await tick();
    expect(sheet.textContent).toContain("Anything else?");

    // "anything else?" never stops until the narrator says done — two adds
    setInput("Mum came too.");
    sendBtn().click();
    await tick();
    expect(sheet.textContent).toContain("Anything else?");
    setInput("Dad drove.");
    sendBtn().click();
    await tick();
    expect(sheet.textContent).toContain("Anything else?");

    action("That's everything").click();
    await tick();
    await tick();

    // the date question is answered in the narrator's own words — no picker
    expect(sheet.textContent).toContain("When did this happen?");
    setInput("the summer of 1970");
    sendBtn().click();
    await tick();
    await tick();
    expect(sheet.textContent).toContain("Who was there?");
    action("I'd rather not say").click();
    await tick();
    await tick();

    // review: assembled verbatim account with Q&A, editable
    const accountText = sheet.querySelector(".sheet-form textarea.field-textarea").value;
    expect(accountText).toContain("A: the summer of 1970");
    expect(accountText).toContain("A: I'd rather not say");

    // the proposed link is a labelled checkbox — untick to drop it, then add a person
    const toggle = [...sheet.querySelectorAll(".link-toggle")][0];
    expect(toggle.textContent).toContain("Marlock");
    toggle.querySelector("input").click();
    const toggled = [...sheet.querySelectorAll(".link-toggle")][0]; // re-rendered on click
    expect(toggled.classList.contains("off")).toBe(true);
    sheet.querySelector(".add-link select").value = "person";
    sheet.querySelector(".add-link input").value = "Harper";
    [...sheet.querySelectorAll(".add-link button")].find((b) => b.textContent === "Add").click();
    await tick();

    // save: the dropped link is filtered out, the added person is in
    [...sheet.querySelectorAll(".sheet-form .btn")].find((b) => b.textContent === "Save story").click();
    await tick();
    await tick();
    expect(sheet.textContent).toContain("it's in the archive");
    expect(state.byId.has("story-x")).toBe(true);
    const saveCall = fetchMock.mock.calls.find(([u]) => u === "/api/save");
    const payload = JSON.parse(saveCall[1].body);
    expect(payload.who).toBe("Alex Hale"); // the session identity
    expect(payload.anchor).toEqual(ANCHOR);
    expect(payload.account).toContain("A: the summer of 1970");
    // facts: the assessment's event-date plus the typed answer as a pending
    // fact — the server asks the model to assert the value (docs/CHAT-UX.md)
    expect(payload.facts).toEqual([
      { kind: "event_date", text: "May 1963", value: "1963-05", precision: "month" },
      {
        kind: "event_date",
        entity: null,
        text: "the summer of 1970",
        value: null,
        precision: null,
        status: "confirmed",
      },
    ]);
    expect(payload.extractions).toEqual([
      { kind: "person", name: "Harper", match: null, bucket: "proposed", on: true, reason: "added by the narrator" },
    ]);
  });

  it("saves an abandoned session as a draft — nothing told is lost", async () => {
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-draft",
            story: { id: "story-draft", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockClear(); // the previous test's global stub must not leak
    const state = { ...STATE };
    const sheet = await openSheetVia(state);
    setInput("A half-told memory.");
    sendBtn().click();
    await tick();
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click(); // abandon mid-flow
    await tick();
    expect(fetchMock).toHaveBeenCalledWith("/api/save", expect.anything());
    expect(document.querySelector(".sheet")).toBeNull();
  });

  it("an abandoned session saves exactly one draft, however often it closes", async () => {
    // close + unload in the same teardown must never pile up copies
    // (user, 2026-08-03 — eight identical drafts once appeared in the archive)
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-draft",
            story: { id: "story-draft", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockClear(); // the previous test's global stub must not leak
    const state = { ...STATE };
    const sheet = await openSheetVia(state);
    setInput("A half-told memory.");
    sendBtn().click();
    await tick();
    // close the sheet twice and fire unload — one draft save, not three
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    window.dispatchEvent(new Event("beforeunload"));
    window.dispatchEvent(new Event("beforeunload"));
    await tick();
    await tick();
    const draftSaves = fetchMock.mock.calls.filter(([u]) => u === "/api/save");
    expect(draftSaves.length).toBe(1);
    expect(JSON.parse(draftSaves[0][1].body).status).toBe("draft");
  });

  it('a "who was there" question picks several people, then finishes', async () => {
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/assess")
        return Promise.resolve(
          okJson({
            ok: true,
            title: "The trips",
            extractions: [],
            facts: [],
            questions: [
              { text: "Who was there?", why: "", skippable: true, suggestions: ["Mum", "Dad"], type: "people" },
              { text: "Anything else about the yard?", why: "", skippable: true, suggestions: [] },
            ],
          }),
        );
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-x",
            story: { id: "story-x", type: "story", title: "T", story: "told", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = { ...STATE };
    const sheet = await openSheetVia(state);
    setInput("We went to Marlock.");
    sendBtn().click();
    await tick();
    action("That's everything").click();
    await tick();
    await tick();

    // the people question: tap a suggestion, type an own value, finish
    expect(sheet.textContent).toContain("Who was there?");
    action("Mum").click();
    await tick();
    const pills = [...sheet.querySelectorAll(".chat-selection .chip-label")].map((c) => c.textContent);
    expect(pills).toEqual(["Mum"]);
    setInput("Harper"); // entering an own value is an option — the input is an autocomplete
    sendBtn().click();
    await tick();
    const pills2 = [...sheet.querySelectorAll(".chat-selection .chip-label")].map((c) => c.textContent);
    expect(pills2).toEqual(["Mum", "Harper"]);
    expect(sheet.querySelector(".chat-bar .ac")).toBeTruthy(); // autocomplete in the chat box

    action("That's everyone").click();
    await tick();
    await tick();
    expect(sheet.textContent).toContain("Anything else about the yard?");
    action("Skip").click();
    await tick();
    await tick();

    [...sheet.querySelectorAll(".sheet-form .btn")].find((b) => b.textContent === "Save story").click();
    await tick();
    await tick();
    const saveCall = fetchMock.mock.calls.find(([u]) => u === "/api/save");
    const payload = JSON.parse(saveCall[1].body);
    expect(payload.account).toContain("A: Mum, Harper");
    // every named person becomes a proposed extraction for the review
    expect(payload.extractions).toEqual([
      { kind: "person", name: "Mum", match: null, bucket: "proposed", on: true, reason: "the narrator named them" },
      { kind: "person", name: "Harper", match: null, bucket: "proposed", on: true, reason: "the narrator named them" },
    ]);
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
  });

  it("openDraft resumes at the review, pre-filled from the sidecar", async () => {
    // the owner comes back from dinner: their draft opens at the review —
    // account text, title, who and every already-linked entity as a toggle
    localStorage.setItem("loft.narrator", "Alex");
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
      byId: new Map(),
    };
    const draft = {
      id: "story-d1",
      title: "The Mirosa",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "The Mirosa was moored alongside, and the crew babysat me.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [{ id: "p-alex", status: "proposed" }],
      places: [],
      themes: [],
      items: [],
      facts: [
        { kind: "dob", entity: "p-alex", text: "", value: "1981-09-15", precision: "exact", status: "confirmed" },
      ],
    };
    openDraft(state, draft);
    await tick();
    const form = document.querySelector(".sheet-form");
    expect(form).toBeTruthy();
    expect(form.querySelector("textarea.field-textarea").value).toBe(draft.story);
    expect(form.querySelector("input.field").value).toBe("The Mirosa");
    // the linked person is a toggle to re-verify, not a hidden assumption
    expect([...form.querySelectorAll(".link-toggle")].map((t) => t.textContent).join()).toContain("Alex Hale");
    // closing saves nothing — the draft already exists (no copy drafts)
    [...document.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
    expect(document.querySelector(".sheet")).toBeNull();
  });

  it("an abandoned mid-question draft carries the full chat transcript", async () => {
    // a reboot or a distraction must be reconstructible later — the draft
    // persists who, every message, the assessment, and where the flow was
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/assess")
        return Promise.resolve(
          okJson({
            ok: true,
            title: "The trips",
            extractions: [],
            facts: [],
            questions: [{ text: "Who was there?", why: "", skippable: true, suggestions: ["Mum"], type: "people" }],
          }),
        );
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-draft",
            story: { id: "story-draft", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = { ...STATE };
    const sheet = await openSheetVia(state);
    setInput("We went to Marlock with Mum.");
    sendBtn().click();
    await tick();
    action("That's everything").click();
    await tick();
    await tick();
    expect(sheet.textContent).toContain("Who was there?");
    action("Mum").click(); // a mid-people-question pause
    await tick();
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
    await tick();
    const saveCall = fetchMock.mock.calls.find(([u]) => u === "/api/save");
    const payload = JSON.parse(saveCall[1].body);
    expect(payload.chat.who).toBe("Alex Hale"); // the session identity
    expect(payload.chat.stage).toBe("questions");
    expect(payload.chat.entries).toEqual([{ kind: "initial", text: "We went to Marlock with Mum." }]);
    expect(payload.chat.questions.length).toBe(1);
    expect(payload.chat.questions[0].type).toBe("people");
    expect(payload.chat.facts).toEqual([]);
    expect(payload.chat.extractions).toEqual([
      { kind: "person", name: "Mum", match: null, bucket: "proposed", on: true, reason: "the narrator named them" },
    ]);
  });

  it("a resumed draft replays the chat up to where the narrator was", async () => {
    localStorage.setItem("loft.narrator", "Alex");
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
      byId: new Map(),
    };
    const draft = {
      id: "story-d1",
      title: "The trips",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock with Mum.\n\nQ: Who was there?\nA: Mum",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
      chat: {
        who: "Alex",
        stage: "questions",
        entries: [{ kind: "initial", text: "We went to Marlock with Mum." }],
        questions: [{ text: "Who was there?", why: "", skippable: true, suggestions: ["Mum"], type: "people" }],
        questionIndex: 0, // the live question — the narrator paused mid-answer
        facts: [],
        extractions: [
          { kind: "person", name: "Mum", match: null, bucket: "proposed", on: true, reason: "the narrator named them" },
        ],
      },
    };
    openDraft(state, draft);
    await tick();
    await tick();
    const sheet = document.querySelector(".sheet");
    // the transcript is reconstructed: the story bubble, the question, the picked pill
    const bubbles = [...sheet.querySelectorAll(".bubble-user")].map((b) => b.textContent);
    expect(bubbles).toContain("We went to Marlock with Mum.");
    expect(sheet.textContent).toContain("Who was there?");
    expect([...sheet.querySelectorAll(".chat-selection .chip-label")].map((c) => c.textContent)).toEqual(["Mum"]);
    // the flow is live: the narrator can keep answering
    const peopleAc = sheet.querySelector(".chat-bar .ac .field");
    expect(peopleAc).toBeTruthy();
    peopleAc.value = "Dad";
    peopleAc.dispatchEvent(new Event("input"));
    sheet.querySelector(".chat-bar").lastElementChild.click();
    await tick();
    expect([...sheet.querySelectorAll(".chat-selection .chip-label")].map((c) => c.textContent)).toEqual([
      "Mum",
      "Dad",
    ]);
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
  });

  it("a resumed draft never shows the story prompt twice (review, 2026-08-07)", async () => {
    const state = { ...STATE };
    const draft = {
      id: "story-d1",
      title: "The trips",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock with Mum.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
      chat: {
        who: "Alex",
        stage: "questions",
        entries: [{ kind: "initial", text: "We went to Marlock with Mum." }],
        questions: [{ text: "Who was there?", why: "", skippable: true, suggestions: ["Mum"], type: "people" }],
        questionIndex: 0,
        facts: [],
        extractions: [],
      },
    };
    openDraft(state, draft);
    await tick();
    await tick();
    const sheet = document.querySelector(".sheet");
    const prompts = [...sheet.querySelectorAll(".bubble-ai .bubble-text")]
      .map((b) => b.textContent)
      .filter((t) => t.includes("What do you remember"));
    expect(prompts).toHaveLength(1); // the fresh-flow prompt must not replay on top of the resume prompt
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
  });

  it("a draft auto-saves the transcript while the narrator types, superseding in place", async () => {
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-draft",
            story: { id: "story-draft", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const ftick = () => vi.advanceTimersByTimeAsync(0); // timers are fake — a 0ms tick is advanced, not awaited
    const state = { ...STATE };
    const section = memoriesSection(state, { title: "T", stories: [], buttonLabel: "Add a memory", anchor: ANCHOR });
    section.querySelector("button.btn").click(); // openSheetVia awaits a real tick — open inline instead
    await ftick();
    const sheet = document.querySelector(".sheet");
    setInput("The first line of the memory.");
    sendBtn().click();
    await ftick();
    await vi.advanceTimersByTimeAsync(2500); // the debounce fires — a draft lands
    await ftick();
    const firstSave = fetchMock.mock.calls.find(([u]) => u === "/api/save");
    expect(firstSave).toBeTruthy();
    const firstPayload = JSON.parse(firstSave[1].body);
    expect(firstPayload.chat.entries).toEqual([{ kind: "initial", text: "The first line of the memory." }]);
    expect(firstPayload.id).toBeUndefined(); // the first save mints the draft id
    setInput("And a second line.");
    sendBtn().click();
    await ftick();
    await vi.advanceTimersByTimeAsync(2500);
    await ftick();
    const saves = fetchMock.mock.calls.filter(([u]) => u === "/api/save");
    expect(saves.length).toBe(2);
    const second = JSON.parse(saves[1][1].body);
    expect(second.id).toBe("story-draft"); // superseding the server-returned id — no pile of drafts
    expect(second.chat.entries.length).toBe(2);
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
  });

  it("completing a resumed draft replaces it in memory — no stale draft card", async () => {
    localStorage.setItem("loft.narrator", "Alex");
    const fetchMock = vi.fn((url) => {
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-d1",
            story: { id: "story-d1", status: "catalogued", title: "Done" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const draft = {
      id: "story-d1",
      title: "The trips",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
    }; // a legacy draft — no chat, resume at review
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
      items: [draft],
      byId: new Map([[draft.id, draft]]),
    };
    openDraft(state, draft);
    await tick();
    await tick();
    expect(document.querySelector(".sheet-form")).toBeTruthy();
    [...document.querySelectorAll(".sheet-form .btn")].find((b) => b.textContent === "Save story").click();
    await tick();
    await tick();
    // the merged catalogued story REPLACES the draft entry — one per id
    expect(state.items.filter((it) => it.id === "story-d1").length).toBe(1);
    expect(state.byId.get("story-d1").status).toBe("catalogued");
  });

  it("abandoning a draft tombstones it and closes without saving a copy", async () => {
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/delete") return Promise.resolve(okJson({ ok: true }));
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    localStorage.setItem("loft.narrator", "Alex");
    const draft = {
      id: "story-d1",
      title: "Half a memory",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
      chat: {
        who: "Alex",
        stage: "story",
        entries: [{ kind: "initial", text: "We went to Marlock." }],
        questions: [],
        questionIndex: 0,
        facts: [],
        extractions: [],
      },
    };
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
      items: [draft],
      byId: new Map([[draft.id, draft]]),
    };
    openDraft(state, draft);
    await tick();
    await tick();
    // the two-step abandon: first click asks, second confirms
    const btn = [...document.querySelectorAll(".sheet-head button")].find((b) => b.textContent === "Abandon");
    expect(btn).toBeTruthy();
    btn.click();
    expect(btn.textContent).toContain("really");
    btn.click();
    await tick();
    await tick();
    const del = fetchMock.mock.calls.find(([u]) => u === "/api/delete");
    expect(del).toBeTruthy();
    expect(JSON.parse(del[1].body).id).toBe("story-d1");
    expect(document.querySelector(".sheet")).toBeNull();
    // no draft-copy save on abandon — the draft is gone, not re-captured
    expect(fetchMock.mock.calls.filter(([u]) => u === "/api/save").length).toBe(0);
    expect(state.items.some((it) => it.id === "story-d1")).toBe(false);
    expect(state.byId.has("story-d1")).toBe(false);
  });

  it("abandon with nothing told just closes — no delete call", async () => {
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const sheet = await openSheetVia({ ...STATE });
    const btn = [...document.querySelectorAll(".sheet-head button")].find((b) => b.textContent === "Abandon");
    btn.click(); // no confirm step needed — nothing was told
    await tick();
    expect(document.querySelector(".sheet")).toBeNull();
    expect(fetchMock.mock.calls.some(([u]) => u === "/api/delete")).toBe(false);
    void sheet;
  });

  it("a failed review save re-enables the button so the redactions can be retried", async () => {
    // review, 2026-08-03: a failed save must never strand the narrator's
    // edits behind a disabled button (the error note says "Try again")
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save") return Promise.resolve(okJson({ ok: false }, 503));
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    localStorage.setItem("loft.narrator", "Alex");
    const draft = {
      id: "story-d1",
      title: "Half a memory",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
    };
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
      items: [draft],
      byId: new Map([[draft.id, draft]]),
    };
    openDraft(state, draft);
    await tick();
    await tick();
    const saveBtn = [...document.querySelectorAll(".sheet-form .btn")].find((b) => b.textContent === "Save story");
    saveBtn.click();
    await tick();
    await tick();
    expect(saveBtn.disabled).toBe(false); // retry is possible
    expect(document.querySelector(".sheet-form")).toBeTruthy(); // the review is still there
    [...document.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click(); // no leaked unload listener
    await tick();
  });

  it("a first-time narrator's draft save merges their minted person record", async () => {
    // review, 2026-08-03: a new narrator (Zofia, not in the cast) is minted
    // p-zofia-kowalski on the server — the draft save must bring that record
    // into state, or they can never see their own draft
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-d1",
            story: {
              id: "story-d1",
              type: "story",
              title: "A half-memory",
              story: "half",
              status: "draft",
              told_by: "p-zofia-kowalski",
            },
            people: [{ id: "p-zofia-kowalski", name: "Zofia Kowalski", aliases: [], relation: "added from a story" }],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = { ...STATE };
    const sheet = await openSheetVia(state);
    setInput("Zofia Kowalski"); // not in the cast — the flow flags a new person
    sendBtn().click();
    await tick();
    setInput("A half-told memory.");
    sendBtn().click();
    await tick();
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click(); // abandon
    await tick();
    await tick();
    expect(state.people.some((p) => p.id === "p-zofia-kowalski" && p.name === "Zofia Kowalski")).toBe(true);
  });

  it("abandon waits for an in-flight draft save, then deletes it — no orphan", async () => {
    // reviewer, 2026-08-03: confirming Abandon while the auto-save fetch is
    // still in flight must not leave a draft the narrator thought they'd
    // discarded (draftId is still null at confirm time)
    let resolveSave;
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save")
        return new Promise((r) => {
          resolveSave = r;
        });
      if (url === "/api/delete") return Promise.resolve(okJson({ ok: true }));
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const ftick = () => vi.advanceTimersByTimeAsync(0);
    const state = { ...STATE };
    const section = memoriesSection(state, { title: "T", stories: [], buttonLabel: "Add a memory", anchor: ANCHOR });
    section.querySelector("button.btn").click();
    await ftick();
    setInput("A half-told memory.");
    sendBtn().click();
    await ftick();
    await vi.advanceTimersByTimeAsync(1600); // the auto-save fires — its fetch is pending
    await ftick();
    const abandonBtn = [...document.querySelectorAll(".sheet-head button")].find((b) => b.textContent === "Abandon");
    abandonBtn.click();
    abandonBtn.click(); // confirmed while the draft save is unresolved
    await ftick();
    expect(fetchMock.mock.calls.some(([u]) => u === "/api/delete")).toBe(false); // waits, does not orphan
    resolveSave(
      okJson({ ok: true, id: "story-d1", story: { id: "story-d1", status: "draft" }, people: [], places: [] }),
    );
    await ftick();
    await ftick();
    const del = fetchMock.mock.calls.find(([u]) => u === "/api/delete");
    expect(del).toBeTruthy();
    expect(JSON.parse(del[1].body).id).toBe("story-d1"); // the landed draft is deleted
    expect(document.querySelector(".sheet")).toBeNull();
  });

  it("a resumed draft keeps its original anchor through the save", async () => {
    // reviewer, 2026-08-03: the anchor (the page the narrator started from)
    // must survive in the transcript — a draft started on a theme page must
    // not re-anchor itself to a null item on completion
    localStorage.setItem("loft.narrator", "Alex");
    const fetchMock = vi.fn((url) => {
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-d1",
            story: { id: "story-d1", status: "catalogued" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const themeAnchor = { kind: "theme", id: "t-the-boats", name: "The boats" };
    const draft = {
      id: "story-d1",
      title: "The trips",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
      chat: {
        who: "Alex",
        stage: "review",
        anchor: themeAnchor,
        entries: [{ kind: "initial", text: "We went to Marlock." }],
        questions: [],
        questionIndex: 0,
        facts: [],
        extractions: [],
      },
    };
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
      items: [draft],
      byId: new Map([[draft.id, draft]]),
    };
    openDraft(state, draft);
    await tick();
    await tick();
    expect(document.querySelector(".sheet-form")).toBeTruthy();
    [...document.querySelectorAll(".sheet-form .btn")].find((b) => b.textContent === "Save story").click();
    await tick();
    await tick();
    const saveCall = fetchMock.mock.calls.find(([u]) => u === "/api/save");
    expect(JSON.parse(saveCall[1].body).anchor).toEqual(themeAnchor);
  });

  it("picking a cast member in the multi-select links them, never re-mints", async () => {
    // reviewer, 2026-08-03: picking "Mum" must match p-mum, not mint p-mum-2
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/assess")
        return Promise.resolve(
          okJson({
            ok: true,
            title: "T",
            extractions: [],
            facts: [],
            questions: [{ text: "Who was there?", why: "", skippable: true, suggestions: ["Mum"], type: "people" }],
          }),
        );
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-d1",
            story: { id: "story-d1", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = {
      ...STATE,
      people: [
        { id: "p-alex", name: "Alex Hale", aliases: ["Alex"] },
        { id: "p-mum", name: "Nora Hale", aliases: ["Mum", "Mummy"] },
      ],
    };
    const sheet = await openSheetVia(state);
    setInput("We went to Marlock with Mum.");
    sendBtn().click();
    await tick();
    action("That's everything").click();
    await tick();
    await tick();
    action("Mum").click(); // a cast member — links, does not mint
    await tick();
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click(); // the draft carries the picks
    await tick();
    await tick();
    const saveCall = fetchMock.mock.calls.find(([u]) => u === "/api/save");
    const picked = JSON.parse(saveCall[1].body).chat.extractions.find((ex) => ex.name === "Mum");
    expect(picked.match).toBe("p-mum");
  });

  it("the review's add-person row links a cast member by name", async () => {
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/assess")
        return Promise.resolve(okJson({ ok: true, title: "T", extractions: [], facts: [], questions: [] }));
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-d1",
            story: { id: "story-d1", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = {
      ...STATE,
      people: [
        { id: "p-alex", name: "Alex Hale", aliases: ["Alex"] },
        { id: "p-mum", name: "Nora Hale", aliases: ["Mum", "Mummy"] },
      ],
    };
    const sheet = await openSheetVia(state);
    setInput("We went to Marlock.");
    sendBtn().click();
    await tick();
    action("That's everything").click();
    await tick();
    await tick();
    sheet.querySelector(".add-link input").value = "Mum";
    [...sheet.querySelectorAll(".add-link button")].find((b) => b.textContent === "Add").click();
    await tick();
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
    await tick();
    const saveCall = fetchMock.mock.calls.find(([u]) => u === "/api/save");
    const added = JSON.parse(saveCall[1].body).chat.extractions.find((ex) => ex.name === "Mum");
    expect(added.match).toBe("p-mum");
  });

  it("removing a picked person's pill drops their proposed link too", async () => {
    // reviewer, 2026-08-03: the X on a pick must not leave a stale extraction
    // behind — the review would otherwise offer a link the narrator removed
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/assess")
        return Promise.resolve(
          okJson({
            ok: true,
            title: "T",
            extractions: [],
            facts: [],
            questions: [
              { text: "Who was there?", why: "", skippable: true, suggestions: ["Mum", "Dad"], type: "people" },
            ],
          }),
        );
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-d1",
            story: { id: "story-d1", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = { ...STATE, people: [{ id: "p-mum", name: "Nora Hale", aliases: ["Mum"] }] };
    const sheet = await openSheetVia(state);
    setInput("We went to Marlock with Mum and Dad.");
    sendBtn().click();
    await tick();
    action("That's everything").click();
    await tick();
    await tick();
    action("Mum").click(); // picked
    await tick();
    const mumX = [...sheet.querySelectorAll(".chat-selection .chip-remove")].find(
      (x) => x.getAttribute("aria-label") === "Remove Mum",
    );
    mumX.click(); // removed — the pill AND the proposed link
    await tick();
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
    await tick();
    const saveCall = fetchMock.mock.calls.find(([u]) => u === "/api/save");
    const extras = JSON.parse(saveCall[1].body).chat.extractions;
    expect(extras.some((ex) => ex.name === "Mum")).toBe(false);
  });

  it("tab close during the final save never mints a competing draft", async () => {
    // reviewer, 2026-08-03: beforeunload while the catalogued save is in
    // flight must not fire a draft save — a stale draft must never supersede
    // the finished story
    let resolveSave;
    const fetchMock = vi.fn((url) => {
      if (url === "/api/save")
        return new Promise((r) => {
          resolveSave = r;
        });
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    localStorage.setItem("loft.narrator", "Alex");
    const draft = {
      id: "story-d1",
      title: "Half",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
    };
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
      items: [draft],
      byId: new Map([[draft.id, draft]]),
    };
    openDraft(state, draft);
    await tick();
    await tick();
    [...document.querySelectorAll(".sheet-form .btn")].find((b) => b.textContent === "Save story").click();
    await tick(); // the final save is now in flight
    window.dispatchEvent(new Event("beforeunload")); // the tab closes
    await tick();
    const saves = fetchMock.mock.calls.filter(([u]) => u === "/api/save");
    expect(saves.length).toBe(1); // only the final save — no draft re-save
    resolveSave(
      okJson({ ok: true, id: "story-d1", story: { id: "story-d1", status: "catalogued" }, people: [], places: [] }),
    );
    await tick();
  });

  it("the header X during the final save never mints a competing draft", async () => {
    // reviewer, 2026-08-03: close() (the header X) must honour the final
    // save in flight just like beforeunload does
    let resolveSave;
    const fetchMock = vi.fn((url) => {
      if (url === "/api/save")
        return new Promise((r) => {
          resolveSave = r;
        });
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    localStorage.setItem("loft.narrator", "Alex");
    const draft = {
      id: "story-d1",
      title: "Half",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
    };
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
      items: [draft],
      byId: new Map([[draft.id, draft]]),
    };
    openDraft(state, draft);
    await tick();
    await tick();
    [...document.querySelectorAll(".sheet-form .btn")].find((b) => b.textContent === "Save story").click();
    await tick(); // the final save is in flight
    [...document.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click(); // the X
    await tick();
    const saves = fetchMock.mock.calls.filter(([u]) => u === "/api/save");
    expect(saves.length).toBe(1); // only the final save — close mints no draft
    resolveSave(
      okJson({ ok: true, id: "story-d1", story: { id: "story-d1", status: "catalogued" }, people: [], places: [] }),
    );
    await tick();
  });

  it("words typed during an in-flight draft save are re-queued, never skipped", async () => {
    // reviewer, 2026-08-03: the coalescing guard skipped a save while one
    // was in flight and never re-scheduled — the newest words waited for the
    // next change or close
    let resolveSave;
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save")
        return new Promise((r) => {
          resolveSave = r;
        });
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const ftick = () => vi.advanceTimersByTimeAsync(0);
    const state = { ...STATE };
    const section = memoriesSection(state, { title: "T", stories: [], buttonLabel: "Add a memory", anchor: ANCHOR });
    section.querySelector("button.btn").click();
    await ftick();
    setInput("The first line.");
    sendBtn().click();
    await ftick();
    await vi.advanceTimersByTimeAsync(1600); // save 1 fires — its fetch is pending
    await ftick();
    setInput("The second line, typed mid-save.");
    sendBtn().click();
    await ftick();
    await vi.advanceTimersByTimeAsync(1600); // the timer fires while saving — must re-queue
    await ftick();
    resolveSave(
      okJson({ ok: true, id: "story-d1", story: { id: "story-d1", status: "draft" }, people: [], places: [] }),
    );
    await ftick();
    await ftick();
    const saves = fetchMock.mock.calls.filter(([u]) => u === "/api/save");
    expect(saves.length).toBe(2); // the re-queued save followed the in-flight one
    const last = JSON.parse(saves[saves.length - 1][1].body);
    expect(last.chat.entries.length).toBe(2); // and it carries the newest words
  });

  it("abandon with a pending re-save never resurrects the tombstoned draft", async () => {
    // reviewer, 2026-08-03: the round-13 re-queue could fire after an
    // abandon and supersede the tombstone — the draft would come back
    let resolveSave;
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save")
        return new Promise((r) => {
          resolveSave = r;
        });
      if (url === "/api/delete") return Promise.resolve(okJson({ ok: true }));
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const ftick = () => vi.advanceTimersByTimeAsync(0);
    const state = { ...STATE };
    const section = memoriesSection(state, { title: "T", stories: [], buttonLabel: "Add a memory", anchor: ANCHOR });
    section.querySelector("button.btn").click();
    await ftick();
    setInput("A half-told memory.");
    sendBtn().click();
    await ftick();
    await vi.advanceTimersByTimeAsync(1600); // save 1 in flight
    await ftick();
    setInput("More words mid-save."); // resavePending gets set
    sendBtn().click();
    await ftick();
    const abandonBtn = [...document.querySelectorAll(".sheet-head button")].find((b) => b.textContent === "Abandon");
    abandonBtn.click();
    abandonBtn.click(); // abandon waits for the in-flight save, then deletes
    await ftick();
    resolveSave(
      okJson({ ok: true, id: "story-d1", story: { id: "story-d1", status: "draft" }, people: [], places: [] }),
    );
    await ftick();
    await ftick();
    expect(document.querySelector(".sheet")).toBeNull();
    const deletes = fetchMock.mock.calls.filter(([u]) => u === "/api/delete");
    expect(deletes.length).toBe(1);
    // the re-queued save must NOT run after the tombstone
    const savesAfterDelete = fetchMock.mock.calls.filter(
      ([u], i) => u === "/api/save" && i > fetchMock.mock.calls.findIndex((c) => c[0] === "/api/delete"),
    );
    expect(savesAfterDelete.length).toBe(0);
  });

  it("merging a saved story's people never duplicates cast members", async () => {
    // reviewer, 2026-08-03: save and saveDraft pushed body.people blindly —
    // a resumed draft's already-merged person could land twice in state
    const fetchMock = vi.fn((url) => {
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-d1",
            story: { id: "story-d1", status: "catalogued" },
            people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    localStorage.setItem("loft.narrator", "Alex");
    const draft = {
      id: "story-d1",
      title: "Half",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "We went to Marlock.",
      comment_on: null,
      recorded: "2026-08-03",
      people: [],
      places: [],
      themes: [],
      items: [],
      facts: [],
    };
    const state = {
      ...STATE,
      people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }], // already in the cast
      items: [draft],
      byId: new Map([[draft.id, draft]]),
    };
    openDraft(state, draft);
    await tick();
    await tick();
    [...document.querySelectorAll(".sheet-form .btn")].find((b) => b.textContent === "Save story").click();
    await tick();
    await tick();
    expect(state.people.filter((p) => p.id === "p-alex").length).toBe(1);
  });

  it("an unavailable AI tells the narrator instead of silently degrading", async () => {
    // reviewer, 2026-08-03: assess failing must be said out loud — the
    // narrator otherwise sees an empty review and wonders where the links went
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/assess") return Promise.resolve(okJson({ ok: false }, 503));
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = { ...STATE };
    const sheet = await openSheetVia(state);
    setInput("We went to Marlock.");
    sendBtn().click();
    await tick();
    action("That's everything").click();
    await tick();
    await tick();
    await tick();
    expect(sheet.textContent).toContain("couldn't read"); // the narrator is told
    [...sheet.querySelectorAll(".btn")].find((b) => b.getAttribute("aria-label") === "Close").click();
    await tick();
  });

  it("opening the capture twice keeps a single sheet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(okJson({ ok: true }, 200))),
    );
    const state = { ...STATE };
    const section = memoriesSection(state, { title: "T", stories: [], buttonLabel: "Add a memory", anchor: ANCHOR });
    section.querySelector("button.btn").click();
    await tick();
    section.querySelector("button.btn").click(); // a second open must be a no-op
    await tick();
    expect(document.querySelectorAll(".sheet-overlay").length).toBe(1);
  });

  it("a reboot (beforeunload) still saves the in-progress account as a draft", async () => {
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") return Promise.resolve(okJson({ ok: true }));
      if (url === "/api/save")
        return Promise.resolve(
          okJson({
            ok: true,
            id: "story-draft",
            story: { id: "story-draft", status: "draft" },
            people: [],
            places: [],
          }),
        );
      return Promise.resolve(okJson({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = { ...STATE };
    await openSheetVia(state);
    setInput("The bearded visitor terrified me.");
    sendBtn().click();
    await tick();
    window.dispatchEvent(new Event("beforeunload")); // the reboot that lost the Bearded Visitor
    await tick();
    expect(fetchMock).toHaveBeenCalledWith("/api/save", expect.anything());
  });
});

describe("memoriesSection render-once (2026-08-06)", () => {
  it("never re-shows a story the page already rendered", () => {
    const story = { id: "s1", title: "Told elsewhere", type: "story", date: "1963-06", date_precision: "month", recorded: "2026-08-03", story: "x", told_by: "p-alex", places: [], people: [], themes: [], assets: [] };
    const state = { people: [{ id: "p-alex", name: "Alex" }] };
    const main = document.createElement("main");
    main.append(memoriesSection(state, { title: "Memories", stories: [story], buttonLabel: "Add", anchor: { kind: "place", id: "pl-x", name: "X" }, exclude: ["s1"] }));
    expect(main.textContent).not.toContain("Told elsewhere");
    expect(main.textContent).toContain("No stories yet");
    main.replaceChildren(memoriesSection(state, { title: "Memories", stories: [story], buttonLabel: "Add", anchor: { kind: "place", id: "pl-x", name: "X" } }));
    expect(main.textContent).toContain("Told elsewhere");
  });
});
