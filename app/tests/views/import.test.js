import { describe, expect, it, beforeEach, vi } from "vitest";
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
});

const tick = () => new Promise((r) => setTimeout(r, 0));
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
                ? "Done — I've noted Pearl Whitlock as your recollection."
                : "Done — Pearl Whitlock is recorded as confirmed.",
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
    chip(main, "Record as confirmed").click();
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
    chip(main, "Record as estimated").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("estimated");
    expect(decided.basis.text).toBe("I think Mum said Nora was a cousin of some kind, via Pearl's brother.");
    expect(bubbles(main).some((b) => b.includes("noted Pearl Whitlock as your recollection"))).toBe(true);
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
    chip(main, "Record as estimated").click();
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
    chip(main, "Record as estimated").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("estimated");
    expect(decided.basis.text).toContain("Not sure about the brother link");
    expect(bubbles(main).some((b) => b.includes("noted Pearl Whitlock as your recollection"))).toBe(true);
  });

  it("off-topic answers are steered back — never recorded", async () => {
    stubFetch({
      relevant: "false",
      note: "the house on Victoria Avenue",
      message: "That's about the house on Victoria Avenue — let's come back to Pearl Whitlock: do you think the link's right?",
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
          json: async () => ({ ok: true, person: { id: body.person_id, name: "X" }, message: "Done — Pearl Whitlock is recorded as confirmed." }),
        });
      }),
    );
    setInput(main, "Ah, you're right — it was Walter.");
    send(main);
    await tick();
    chip(main, "Record as confirmed").click();
    await tick();
    expect(fetch.mock.calls.filter(([url]) => url === "/api/review/decide")).toHaveLength(1); // now recorded
    expect(bubbles(main).some((b) => b.includes("recorded as confirmed"))).toBe(true);
  });

  it('"I don\'t know" keeps the import\'s guess as proposed', async () => {
    stubFetch();
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "I don't know").click();
    chip(main, "Keep as proposed").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("pending");
    expect(bubbles(main).some((b) => b.includes("stays as the import's guess for now"))).toBe(true);
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
    chip(main, "Remove it").click();
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
    chip(main, "Record as estimated").click();
    await tick();
    const decided = JSON.parse(decideCall()[1].body);
    expect(decided.decision).toBe("estimated");
    expect(decided.basis.text).toContain("Not sure. I think Mum said Nora was some kind of cousin");
  });

  it('a typed "I don\'t know" concludes — the keep/estimate chips, never a re-ask or confirmation (2026-08-09, the transcript\'s loop)', async () => {
    stubFetch({ confidence: "dont_know", question: "I'll leave her as the import's guess unless you'd like to record what you remember as an estimate." });
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    setInput(main, "I've no idea whether she was his sister — I never met her.");
    send(main);
    await tick();
    const chips = [...main.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent);
    expect(chips).toEqual(expect.arrayContaining(["Keep as proposed", "Record as estimated"]));
    expect(chips).not.toContain("Record as confirmed"); // exhausted uncertainty never confirms
    chip(main, "Keep as proposed").click();
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
      chip(main, "Record as confirmed").click();
      await tick();
    }
    expect(bubbles(main).at(-1)).toContain("That's everyone — 2 confirmed");
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
    expect(main.textContent).toContain("Pearl Whitlock — estimated, from Alex's recollection (2026-08-09): 'Grandma said so'.");
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
