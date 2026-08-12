import { afterEach, describe, expect, it, beforeEach, vi } from "vitest";
import { render } from "../../views/import.js";

const STATE = {
  imports: [{ id: "import-documents", title: "The document import", status: "pending" }],
  people: [
    { id: "p-judith", name: "Pearl Whitlock", relation: "cousin — researcher", status: "proposed" },
    { id: "p-robert", name: "Quentin Whitlock", relation: "unknown", status: "proposed" },
  ],
  relationships: [],
  items: [],
  byId: new Map(),
};

beforeEach(() => {
  vi.unstubAllGlobals();
  vi.useFakeTimers(); // never real timers — every test's independence is visible here (2026-08-11 review)
});

afterEach(async () => {
  // The app's fire-and-forget records (recordMessage, decide, checkText)
  // can outlive a test: a chain still in flight when the next test's
  // beforeEach unstubs the globals lands on a FOREIGN mock — or on the
  // real happy-dom fetch, which resolves relative URLs against its
  // default origin http://localhost:3000 (ECONNREFUSED). 2026-08-11 CI:
  // under the coverage run's slower istanbul transforms, the "kept link"
  // test's chain straddled the boundary and the re-render test saw four
  // phantom message calls. The drain waits until a full macrotask passes
  // with no new fetch call — condition-based, never a fixed tick count —
  // and fails loud if the app never settles. The clock is FAKE, so the
  // drain advances it deterministically instead of waiting wall-clock
  // (2026-08-11 review: real timers are a bug in a test).
  try {
    for (let i = 0; i < 20; i++) {
      const before = fetch?.mock?.calls?.length ?? 0;
      await vi.advanceTimersByTimeAsync(0);
      if ((fetch?.mock?.calls?.length ?? 0) === before) return;
    }
    throw new Error("the app's async work did not settle — a record chain is still in flight");
  } finally {
    vi.useRealTimers(); // the next suite runs on the real clock
  }
});

const tick = () => vi.advanceTimersByTimeAsync(0);
const chip = (main, label) => [...main.querySelectorAll(".chat-quick .chip")].find((b) => b.textContent === label);
const bubbles = (main) => [...main.querySelectorAll(".bubble-text")].map((b) => b.textContent);
const setInput = (main, text) => {
  const input = main.querySelector(".chat-bar .field");
  input.value = text;
  input.dispatchEvent(new Event("input"));
};
const send = (main) => main.querySelector(".chat-bar .btn-primary").click();

/** The text endpoint is scripted per-test; the decide echoes the person
 *  back so the state merge replaces the record. */
function stubFetch({
  relevant = "true",
  contradiction = "false",
  detail = "",
  note = "",
  confidence = "think_so",
  question = "",
  findings = [],
  message = "",
} = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url, init) => {
      const body = JSON.parse(init?.body ?? "{}");
      if (url === "/api/review/text") {
        const auto = findings.length
          ? `The documents show: ${findings.map((f) => (typeof f === "string" ? f : f.text)).join(" ")}`
          : "";
        return Promise.resolve({
          ok: true,
          json: async () => ({
            ok: true,
            relevant,
            contradiction: { found: contradiction, detail },
            confidence,
            note,
            question,
            findings,
            message: message || [auto, question].filter(Boolean).join(" "),
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => {
          if (body.decision === "delete") return { ok: true, person: { id: body.person_id, gone: true }, message: "Done — X is not recorded after all." };
          return {
            ok: true,
            person: {
              id: body.person_id,
              name: "X",
              status: body.decision === "estimated" ? "estimated" : body.decision === "pending" ? "proposed" : undefined,
            },
            message:
              body.decision === "estimated"
                ? "Done — I've recorded Pearl Whitlock as a guess."
                : "Done — Pearl Whitlock joins the tree as a fact.",
          };
        },
      });
    }),
  );
}

const decideCall = () => fetch.mock.calls.find(([url]) => url === "/api/review/decide");

describe("the import review is the chat — one conversation resolves the pending links (2026-08-08/09)", () => {
  it("opens naming the exact claim with the four confidence dispositions — no list", () => {
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, STATE);
    expect(bubbles(main)[0]).toContain("there are 2 people from the documents");
    expect(bubbles(main)[1]).toContain("Next: Pearl Whitlock. The notes describe Pearl Whitlock as cousin — researcher.");
    expect(bubbles(main)[1]).toContain("Does that fit what you remember?"); // the options answer this question
    expect(main.querySelectorAll(".cast-card")).toHaveLength(0); // no people list
    expect([...main.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent)).toEqual([
      "Definitely",
      "I think so",
      "I don't know",
      "Definitely not",
      "I think not",
    ]);
    // the standard free-text affordance: the input stays live beside the
    // chips, and its placeholder names the typing path (2026-08-09)
    expect(main.querySelector(".chat-bar .field").placeholder).toBe("Or type your own answer…");
  });

  it("the claim names the source document, quotes it directly, and links it", () => {
    const state = JSON.parse(JSON.stringify(STATE));
    state.items = [
      {
        id: "doc-2001-email",
        title: "Whitlock family history email, 7 Feb 2001",
        date: "2001-02-07",
        type: "document",
        transcription: "I am researching the Whitlock line and would like to make contact. Pearl Whitlock.",
        people: [{ id: "p-judith", status: "confirmed" }],
      },
    ];
    state.byId = new Map(state.items.map((it) => [it.id, it]));
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    const claim = bubbles(main)[1];
    expect(claim).toContain("Whitlock family history email, 7 Feb 2001 mentions Pearl Whitlock");
    expect(claim).toContain('"I am researching the Whitlock line and would like to make contact."'); // the direct quote
    expect(claim).toContain("The notes describe Pearl Whitlock as cousin — researcher."); // the paraphrase, unquoted
    const link = main.querySelector('.bubble-ai a[href="#/item/doc-2001-email"]');
    expect(link).toBeTruthy(); // the document is linked
  });

  it("the claim quotes the sentence that mentions the person, never the document's opening (2026-08-09, user)", () => {
    const state = JSON.parse(JSON.stringify(STATE));
    state.items = [
      {
        id: "doc-2001-email",
        title: "Whitlock family history email, 7 Feb 2001",
        date: "2001-02-07",
        type: "document",
        transcription:
          "The family archive has grown dusty over the years and I am writing to everyone who might help. " +
          "The notes my aunt left say that Pearl Whitlock was the one who kept the photographs. " +
          "Any memories you can share would be very welcome.",
        people: [{ id: "p-judith", status: "confirmed" }],
      },
    ];
    state.byId = new Map(state.items.map((it) => [it.id, it]));
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    const claim = bubbles(main)[1];
    expect(claim).toContain('"The notes my aunt left say that Pearl Whitlock was the one who kept the photographs."');
    expect(claim).not.toContain("The family archive has grown dusty"); // the opening is not the attestation
  });

  it('"Definitely" asks how you know, then the link is confirmed on your word', async () => {
    stubFetch({ confidence: "definitely", question: "Did you see the record yourself?", findings: ["in the record book, Pearl Whitlock is named as the cousin"] });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "Definitely").click();
    expect(bubbles(main).at(-1)).toBe("How do you know?");
    setInput(main, "I read it in the record book.");
    send(main);
    await tick();
    expect(bubbles(main).at(-1)).toContain("The documents show"); // the digging is said aloud
    expect(bubbles(main).at(-1)).toContain("Did you see the record yourself?"); // the genealogist's question
    chip(main, "Record as fact").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("attested");
    expect(decided.basis.text).toBe("I read it in the record book.");
    expect(decided.basis.by).toBe("the reviewer");
    expect(state.people[0].status).toBeUndefined(); // confirmed — the status dropped
  });

  it('"I think so" records the estimate with your own words as the basis', async () => {
    stubFetch({ question: "Did Mum tell you that personally?" });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "I think so").click();
    expect(bubbles(main).at(-1)).toBe("What do you remember that makes you think so?");
    setInput(main, "I think Mum said Nora was a cousin of some kind, via Pearl's brother.");
    send(main);
    await tick();
    chip(main, "Record as guess").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("estimated");
    expect(decided.basis.text).toBe("I think Mum said Nora was a cousin of some kind, via Pearl's brother.");
    expect(bubbles(main).some((b) => b.includes("recorded Pearl Whitlock as a guess"))).toBe(true);
    expect(state.people[0].status).toBe("estimated");
  });

  it("the provenance answer is kept beside the recollection, never re-asked for", async () => {
    stubFetch({ question: "Did Mum tell you that personally?" });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "I think so").click();
    setInput(main, "I think Mum said Nora was a cousin of some kind.");
    send(main);
    await tick();
    expect(bubbles(main).at(-1)).toBe("Did Mum tell you that personally?"); // the provenance, not a re-ask
    setInput(main, "Yes, she told me herself.");
    send(main);
    await tick();
    chip(main, "Record as guess").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.basis.text).toBe("I think Mum said Nora was a cousin of some kind.");
    expect(decided.basis.note).toContain("Yes, she told me herself."); // the provenance beside it
  });

  it("typing your own answer works — the explicit confirmation follows the digging", async () => {
    stubFetch({
      confidence: "think_so",
      findings: ["in the war record, Walter Whitlock is recorded as dying in 1916"],
      question: "Did Mum tell you that personally?",
    });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    // ignore the chips entirely — just type
    setInput(main, "Not sure about the brother link. But I remember Mum saying one of Nora's siblings died in the war.");
    send(main);
    await tick();
    expect(bubbles(main).some((b) => b.includes("The documents show"))).toBe(true);
    expect(bubbles(main).some((b) => b.includes("in the war record, Walter Whitlock"))).toBe(true); // the documents' terms
    chip(main, "Record as guess").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("estimated");
    expect(decided.basis.text).toContain("Not sure about the brother link");
    expect(bubbles(main).some((b) => b.includes("recorded Pearl Whitlock as a guess"))).toBe(true);
  });

  it("off-topic answers are steered back — never recorded", async () => {
    stubFetch({
      relevant: "false",
      note: "the house on Victoria Avenue",
      message: "That's about the house on Victoria Avenue — let's come back to Pearl Whitlock: does that fit what you remember?",
    });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "Definitely").click();
    setInput(main, "We visited that house every summer.");
    send(main);
    await tick();
    expect(fetch.mock.calls.some(([url]) => url === "/api/review/decide")).toBe(false); // nothing recorded
    expect(bubbles(main).some((b) => b.includes("the house on Victoria Avenue"))).toBe(true); // the steer names the mismatch
    expect(bubbles(main).at(-1)).toContain("Pearl Whitlock"); // the claim is re-asked
  });

  it("a contradiction with the attested facts surfaces and must be resolved before confirming", async () => {
    stubFetch({
      contradiction: "true",
      detail: "the war record attests Walter Whitlock died in 1916",
      message: "That doesn't match the records — the war record attests Walter Whitlock died in 1916. Which is right?",
    });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "Definitely").click();
    setInput(main, "It was Nora who died in the war, I remember that clearly.");
    send(main);
    await tick();
    expect(fetch.mock.calls.some(([url]) => url === "/api/review/decide")).toBe(false); // nothing recorded yet
    expect(bubbles(main).some((b) => b.includes("That doesn't match the records"))).toBe(true);
    expect(bubbles(main).at(-1)).toContain("Which is right?"); // the contradiction is surfaced
    // the resolution is checked again — the scripted stub now reports clear
    vi.stubGlobal(
      "fetch",
      vi.fn((url, init) => {
        const body = JSON.parse(init?.body ?? "{}");
        if (url === "/api/review/text") {
          return Promise.resolve({ ok: true, json: async () => ({ ok: true, relevant: "true", contradiction: { found: "false", detail: "" }, confidence: "definitely", note: "the reviewer corrected it", question: "", findings: [], message: "" }) });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({ ok: true, person: { id: body.person_id, name: "X" }, message: "Done — Pearl Whitlock joins the tree as a fact." }),
        });
      }),
    );
    setInput(main, "Ah, you're right — it was Walter.");
    send(main);
    await tick();
    chip(main, "Record as fact").click();
    await tick();
    expect(fetch.mock.calls.filter(([url]) => url === "/api/review/decide")).toHaveLength(1); // now recorded
    const decided = JSON.parse(decideCall()[1].body);
    // the contradicted words are the basis statement; the typed correction
    // rides as the note BESIDE them — never the other way round
    // (2026-08-11 review)
    expect(decided.basis.text).toBe("It was Nora who died in the war, I remember that clearly.");
    expect(decided.basis.note).toContain("Ah, you're right — it was Walter.");
    expect(bubbles(main).some((b) => b.includes("joins the tree as a fact"))).toBe(true);
  });

  it('"I don\'t know" chats first — only then are the options offered (2026-08-10, user: "don\'t suggest any of these until we\'ve chatted about what they know")', async () => {
    stubFetch();
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "I don't know").click();
    expect(bubbles(main).at(-1)).toBe("What do you remember about them, even a little?"); // chat first, no buttons
    expect(main.querySelectorAll(".chat-quick .chip")).toHaveLength(0);
    setInput(main, "Nothing really — I never met her.");
    send(main);
    await tick();
    // only the options that apply: leave it or record what little they know — never fact, never delete
    expect([...main.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent)).toEqual([
      "Leave for later",
      "Record as guess",
    ]);
    chip(main, "Leave for later").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("pending");
    expect(bubbles(main).some((b) => b.includes("stays out of the tree for now"))).toBe(true);
    expect(state.people[0].status).toBe("proposed"); // untouched
  });

  it('"Definitely not" asks for the explanation and offers removal', async () => {
    stubFetch({ confidence: "definitely_not" });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "Definitely not").click();
    expect(bubbles(main).at(-1)).toBe("What makes you say that?");
    setInput(main, "He was never in the family — a researcher's confusion.");
    send(main);
    await tick();
    chip(main, "Delete").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("delete");
    expect(bubbles(main).some((b) => b.includes("not recorded after all"))).toBe(true);
    expect(state.people.some((p) => p.id === "p-judith")).toBe(false); // gone from the state
  });

  it("an uncertain recollection never dead-ends — the confirmation is offered", async () => {
    stubFetch({ confidence: "unclear", findings: ["in the record book, the Whitlock cousin line is mentioned"] });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    setInput(main, "Not sure. I think Mum said Nora was some kind of cousin — via one of Pearl's brothers?");
    send(main);
    await tick();
    expect(bubbles(main).some((b) => b.includes("The documents show"))).toBe(true); // it dug, never dead-ended
    chip(main, "Record as guess").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("estimated");
    expect(decided.basis.text).toContain("Not sure. I think Mum said Nora was some kind of cousin");
  });

  it('a typed "I don\'t know" concludes — the leave/guess chips, never a re-ask or fact/delete (2026-08-09, the transcript\'s loop; 2026-08-10 vocabulary)', async () => {
    stubFetch({ confidence: "dont_know", question: "I'll leave her as she stands unless you'd like to record what you remember as a guess." });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    setInput(main, "I've no idea whether she was his sister — I never met her.");
    send(main);
    await tick();
    const chips = [...main.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent);
    expect(chips).toEqual(expect.arrayContaining(["Leave for later", "Record as guess"]));
    expect(chips).not.toContain("Record as fact"); // exhausted uncertainty never offers fact
    expect(chips).not.toContain("Delete");
    chip(main, "Leave for later").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("pending");
    expect(state.people[0].status).toBe("proposed"); // untouched
  });

  it("the last link completes the session — the ending summarises and offers the tree", async () => {
    stubFetch({ confidence: "definitely" });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    for (const name of ["Pearl Whitlock", "Quentin Whitlock"]) {
      chip(main, "Definitely").click();
      setInput(main, `The record attests ${name}.`);
      send(main);
      await tick();
      chip(main, "Record as fact").click();
      await tick();
    }
    expect(bubbles(main).at(-1)).toContain("That's everyone — 2 recorded as facts");
    expect([...main.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent)).toContain("See the family tree →");
    expect(state.imports[0].status).toBe("reviewed"); // nothing pending — the home card disappears
  });

  it("the session page shows the review record — the decisions so far", () => {
    const state = JSON.parse(JSON.stringify(STATE));
    state.imports[0].attempts = [
      { started: "2026-08-09T00:00:00+00:00", transcript: [], decisions: [] },
      {
        started: "2026-08-09T10:00:00+00:00",
        transcript: [],
        decisions: [
          { person_id: "p-judith", decision: "estimated", basis: { text: "Grandma said so", by: "Alex", when: "2026-08-09" }, when: "2026-08-09" },
        ],
      },
    ];
    state.imports[0].current = "p-robert";
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    expect(main.textContent).toContain("The review so far");
    expect(main.textContent).toContain("Pearl Whitlock — recorded as a guess, from Alex's recollection (2026-08-09): 'Grandma said so'.");
  });

  it("a resumed session continues from the record's resume point", () => {
    const state = JSON.parse(JSON.stringify(STATE));
    state.imports[0].attempts = [{ started: "2026-08-09T10:00:00+00:00", transcript: [], decisions: [] }];
    state.imports[0].current = "p-robert";
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    expect(bubbles(main)[1]).toContain("Quentin Whitlock"); // the conversation resumes at the last undecided link
  });

  it("shows the finished state when the session has no pending people", () => {
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, { ...STATE, people: [] });
    expect(main.textContent).toContain("Nothing is waiting");
    expect(main.querySelectorAll(".chat")).toHaveLength(0); // no chat to run
  });

  it("unknown import ids get a not-found, never a crash", () => {
    const main = document.createElement("main");
    render(main, { arg: "import-nope", query: new URLSearchParams() }, STATE);
    expect(main.textContent).toContain("Not found");
  });
});


  it("a kept link is never re-asked this walk — it stays proposed as the resume point (2026-08-10 review)", async () => {
    stubFetch({ confidence: "dont_know" });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "I don't know").click();
    setInput(main, "Nothing, really.");
    send(main);
    await tick();
    chip(main, "Leave for later").click();
    await tick();
    // the NEXT link is asked — never the same kept one (the walk used to
    // re-ask the identical link forever because it stays proposed)
    expect(bubbles(main).at(-1)).toContain("Quentin Whitlock");
    expect(state.people[0].status).toBe("proposed"); // untouched — the resume point for a later visit
  });

  it("a re-render does not duplicate the transcript — the start response's lines are not re-recorded (2026-08-10 review)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url, init) => {
        const body = JSON.parse(init?.body ?? "{}");
        if (url === "/api/review/start") {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              ok: true,
              messages: [
                "Thanks for coming back — there are 2 people from the documents I'd like your eyes on.",
                "Next: Pearl Whitlock. The notes describe Pearl Whitlock as cousin — researcher. Does that fit what you remember?",
              ],
            }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => ({ ok: true, person: { id: body.person_id, name: "X" } }) });
      }),
    );
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    await tick();
    await tick();
    // the opening and the resumed claim are already in the attempt — no
    // message-endpoint call lands for them
    expect(fetch.mock.calls.filter(([url]) => url === "/api/review/message")).toHaveLength(0);
  });

  it("a mid-walk re-render never re-asks a link this attempt already decided (2026-08-11 review)", async () => {
    stubFetch();
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    state.imports[0].attempts = [
      {
        started: "2026-08-11T10:00:00+00:00",
        messages: [],
        decisions: [{ person_id: "p-judith", decision: "pending", when: "2026-08-11" }],
      },
    ];
    state.imports[0].current = "p-judith"; // the resume point IS the link this walk decided
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    await tick();
    // the next undecided link is asked — never the one the attempt already
    // left for later (the loop the re-ask used to be)
    expect(bubbles(main).at(-1)).toContain("Quentin Whitlock");
    expect(bubbles(main).some((b) => b.includes("Next: Pearl Whitlock"))).toBe(false);
  });

  it("a re-render after every link was decided ends with the summary — never a re-ask (2026-08-11 review)", async () => {
    stubFetch();
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    state.imports[0].attempts = [
      {
        started: "2026-08-11T10:00:00+00:00",
        messages: [],
        decisions: [
          { person_id: "p-judith", decision: "pending", when: "2026-08-11" },
          { person_id: "p-robert", decision: "pending", when: "2026-08-11" },
        ],
      },
    ];
    state.imports[0].current = "p-robert";
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    await tick();
    expect(bubbles(main).at(-1)).toContain("That's everyone");
    expect(bubbles(main).at(-1)).toContain("2 left for later");
    expect([...main.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent)).toContain("See the family tree →");
  });

  it("a repeated contradiction keeps the first words as the basis — corrections accumulate beside them (2026-08-11 review)", async () => {
    const answers = [
      // first check: the contradiction is surfaced
      { ok: true, relevant: "true", contradiction: { found: "true", detail: "the war record attests Walter Whitlock died in 1916" }, confidence: "definitely", note: "", findings: [], question: "", message: "That doesn't match the records — the war record attests Walter Whitlock died in 1916. Which is right?" },
      // second check: still contradicting — the first words must survive
      { ok: true, relevant: "true", contradiction: { found: "true", detail: "the war record attests Walter Whitlock died in 1916" }, confidence: "definitely", note: "", findings: [], question: "", message: "That doesn't match the records — the war record attests Walter Whitlock died in 1916. Which is right?" },
      // third check: resolved
      { ok: true, relevant: "true", contradiction: { found: "false", detail: "" }, confidence: "definitely", note: "", findings: [], question: "", message: "" },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn((url, init) => {
        const body = JSON.parse(init?.body ?? "{}");
        if (url === "/api/review/text") {
          const answer = answers.shift() ?? answers.at(-1);
          return Promise.resolve({ ok: true, json: async () => answer });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({ ok: true, person: { id: body.person_id, name: "X" }, message: "Done — Pearl Whitlock joins the tree as a fact." }),
        });
      }),
    );
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "Definitely").click();
    setInput(main, "It was Nora who died in the war, I remember that clearly.");
    send(main);
    await tick();
    setInput(main, "No wait — Nora's brother Walter, I think.");
    send(main);
    await tick();
    setInput(main, "Ah, you're right — it was Walter.");
    send(main);
    await tick();
    chip(main, "Record as fact").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    // the family's FIRST words stay the basis; every correction rides
    // beside them — never the other way round (PRD R8, 2026-08-11 review)
    expect(decided.basis.text).toBe("It was Nora who died in the war, I remember that clearly.");
    expect(decided.basis.note).toContain("No wait — Nora's brother Walter, I think.");
    expect(decided.basis.note).toContain("Ah, you're right — it was Walter.");
  });

  it("a failed transcript record is logged, never silently swallowed (2026-08-11 review)", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn((url) => {
        if (url === "/api/review/message") return Promise.reject(new Error("network down"));
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
      }),
    );
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, STATE);
    await tick();
    await tick();
    expect(errorSpy.mock.calls.some((c) => String(c[0]).includes("failed to record a transcript line"))).toBe(true);
    errorSpy.mockRestore();
  });
