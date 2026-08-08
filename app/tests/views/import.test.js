import { describe, expect, it, beforeEach, vi } from "vitest";
import { render } from "../../views/import.js";

const STATE = {
  imports: [{ id: "import-documents", title: "The document import", status: "pending" }],
  people: [
    { id: "p-judith", name: "Pearl Whitlock", relation: "cousin — researcher", status: "proposed" },
    { id: "p-robert", name: "Quentin Whitlock", relation: "unknown", status: "proposed" },
  ],
  relationships: [],
};

beforeEach(() => {
  vi.unstubAllGlobals();
});

const chip = (main, label) => [...main.querySelectorAll(".chat-quick .chip")].find((b) => b.textContent === label);
const bubbles = (main) => [...main.querySelectorAll(".bubble-text")].map((b) => b.textContent);
const setInput = (main, text) => {
  const input = main.querySelector(".chat-bar .field");
  input.value = text;
  input.dispatchEvent(new Event("input"));
};

function stubConfirm() {
  // the confirm echoes the request's id so the state merge replaces the
  // proposed record and the chat can advance
  vi.stubGlobal(
    "fetch",
    vi.fn((url, init) => {
      const body = JSON.parse(init?.body ?? "{}");
      return Promise.resolve({
        ok: true,
        json: async () => ({ ok: true, person: { id: body.id ?? "p-x", name: "X" } }),
      });
    }),
  );
}

describe("the import review is the chat (2026-08-08, user: the unfinished doc import is reviewed in one conversation, not a list of review buttons)", () => {
  it("opens as the review conversation about the first pending person — no list", () => {
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, STATE);
    expect(bubbles(main)[0]).toContain("2 people are still waiting");
    expect(bubbles(main)[1]).toContain("Pearl Whitlock");
    expect(bubbles(main)[1]).toContain("cousin — researcher");
    expect(main.querySelectorAll(".cast-card")).toHaveLength(0); // no people list
    expect([...main.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent)).toEqual([
      "Yes — she's family",
      "No — dismiss her",
    ]);
  });

  it("confirms with a specific kinship term and advances to the next person", async () => {
    stubConfirm();
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "Yes — she's family").click();
    chip(main, "first cousin once removed").click();
    await new Promise((r) => setTimeout(r, 0));
    const confirmCalls = fetch.mock.calls.filter(([url]) => url === "/api/people/confirm");
    expect(JSON.parse(confirmCalls[0][1].body)).toEqual({ id: "p-judith", relation: "first cousin once removed" });
    expect(bubbles(main).at(-1)).toContain("Quentin Whitlock"); // the conversation moved on
    expect(state.people[0].status).toBeUndefined(); // confirmed
  });

  it("dismisses and advances", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ ok: true }) })),
    );
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "No — dismiss her").click();
    await new Promise((r) => setTimeout(r, 0));
    expect(fetch.mock.calls.some(([url, init]) => url === "/api/people/dismiss" && JSON.parse(init.body).id === "p-judith")).toBe(true);
    expect(bubbles(main).at(-1)).toContain("Quentin Whitlock");
    expect(state.people).toHaveLength(1);
  });

  it("resolves the narrator's own words to a precise term and confirms with it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url) => {
        if (url === "/api/review/relate") {
          return Promise.resolve({ ok: true, json: async () => ({ ok: true, term: "first cousin once removed", note: "Nora's first cousin via Fern" }) });
        }
        return Promise.resolve({ ok: true, json: async () => ({ ok: true, person: { id: "p-judith", name: "Pearl Whitlock", relation: "first cousin once removed (Nora's first cousin via Fern)" } }) });
      }),
    );
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    chip(main, "Yes — she's family").click();
    chip(main, "Something else — I'll say it").click();
    setInput(main, "She's my mum's cousin on Fern's side.");
    main.querySelector(".chat-bar .btn-primary").click();
    await new Promise((r) => setTimeout(r, 0));
    const relateCall = fetch.mock.calls.find(([url]) => url === "/api/review/relate");
    expect(JSON.parse(relateCall[1].body)).toEqual({ person_id: "p-judith", text: "She's my mum's cousin on Fern's side." });
    const confirmCall = fetch.mock.calls.find(([url]) => url === "/api/people/confirm");
    expect(JSON.parse(confirmCall[1].body).relation).toContain("first cousin once removed");
    expect(bubbles(main).at(-1)).toContain("Quentin Whitlock"); // still advancing
  });

  it("the last person completes the session — the card leaves the front page", async () => {
    stubConfirm();
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    // review both pending people
    for (const name of ["Pearl Whitlock", "Quentin Whitlock"]) {
      chip(main, "Yes — she's family").click();
      chip(main, "first cousin once removed").click();
      await new Promise((r) => setTimeout(r, 0));
      expect(bubbles(main).some((b) => b.includes(name) && b.includes("confirmed"))).toBe(true);
    }
    expect(bubbles(main).at(-1)).toContain("That's everyone");
    expect(state.imports[0].status).toBe("reviewed"); // nothing pending — the home card disappears
    expect(fetch.mock.calls.filter(([url]) => url === "/api/people/confirm")).toHaveLength(2);
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
