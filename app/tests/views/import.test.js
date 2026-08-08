import { describe, expect, it, beforeEach, vi } from "vitest";
import { render } from "../../views/import.js";

const STATE = {
  imports: [{ id: "import-documents", title: "The document import", status: "pending" }],
  people: [{ id: "p-judith", name: "Pearl Whitlock", relation: "cousin — researcher", status: "proposed" }],
  relationships: [],
};

beforeEach(() => {
  document.querySelector(".sheet-overlay")?.remove();
  vi.unstubAllGlobals();
});

const chip = (label) => [...document.querySelectorAll(".chat-quick .chip")].find((b) => b.textContent === label);
const bubbles = () => [...document.querySelectorAll(".bubble-text")].map((b) => b.textContent);
const setInput = (text) => {
  const input = document.querySelector(".chat-bar .field");
  input.value = text;
  input.dispatchEvent(new Event("input"));
};

describe("the import review is a chat (2026-08-08, user: the pending people are confirmed in the review conversation, not a form)", () => {
  it("lists the pending people with a Review entry, never a form", () => {
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, STATE);
    expect(main.textContent).toContain("Pearl Whitlock");
    const buttons = [...main.querySelectorAll("button")].map((b) => b.textContent.trim());
    expect(buttons).toContain("Review");
    expect(buttons).not.toContain("Confirm"); // no Confirm/Dismiss grid
    expect(buttons).not.toContain("Dismiss");
  });

  it("shows the finished state when the session has no pending people", () => {
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, { ...STATE, people: [] });
    expect(main.textContent).not.toContain("Pearl Whitlock");
    expect(main.textContent).toContain("Nothing is waiting"); // the session is done
  });

  it("unknown import ids get a not-found, never a crash", () => {
    const main = document.createElement("main");
    render(main, { arg: "import-nope", query: new URLSearchParams() }, STATE);
    expect(main.textContent).toContain("Not found");
  });
});

describe("the review conversation (2026-08-08)", () => {
  it("asks whether the person is family, then confirms with a SPECIFIC kinship term", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: true, json: async () => ({ ok: true, person: { id: "p-judith", name: "Pearl Whitlock", relation: "first cousin once removed" } }) }),
      ),
    );
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    [...main.querySelectorAll("button")].find((b) => b.textContent.trim() === "Review").click();
    expect(bubbles()[0]).toContain("cousin — researcher"); // the import's record is on the table
    chip("Yes — she's family").click();
    expect(bubbles()[1]).toContain("In what way");
    chip("first cousin once removed").click();
    await new Promise((r) => setTimeout(r, 0));
    const confirmCall = fetch.mock.calls.find(([url]) => url === "/api/people/confirm");
    expect(JSON.parse(confirmCall[1].body)).toEqual({ id: "p-judith", relation: "first cousin once removed" });
    expect(state.imports[0].status).toBe("reviewed"); // the last pending person completes the session
  });

  it("offers the specific cousin terms for a person the import calls a cousin", async () => {
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, STATE);
    [...main.querySelectorAll("button")].find((b) => b.textContent.trim() === "Review").click();
    chip("Yes — she's family").click();
    const chips = [...document.querySelectorAll(".chat-quick .chip")].map((c) => c.textContent);
    expect(chips).toContain("first cousin");
    expect(chips).toContain("first cousin once removed");
    expect(chips).not.toContain("cousin"); // never a bare cousin
  });

  it("dismisses from the chat when the person is not family", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ ok: true }) })),
    );
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    [...main.querySelectorAll("button")].find((b) => b.textContent.trim() === "Review").click();
    chip("No — dismiss her").click();
    await new Promise((r) => setTimeout(r, 0));
    const dismissCall = fetch.mock.calls.find(([url]) => url === "/api/people/dismiss");
    expect(JSON.parse(dismissCall[1].body)).toEqual({ id: "p-judith" });
    expect(state.people).toEqual([]); // gone from the pending list
    expect(state.imports[0].status).toBe("reviewed");
  });

  it("resolves the narrator's own words to a precise term and confirms with it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url) => {
        if (url === "/api/review/relate") {
          return Promise.resolve({
            ok: true,
            json: async () => ({ ok: true, term: "first cousin once removed", note: "Nora's first cousin via Fern" }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => ({ ok: true, person: { id: "p-judith", name: "Pearl Whitlock", relation: "first cousin once removed (Nora's first cousin via Fern)" } }) });
      }),
    );
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    [...main.querySelectorAll("button")].find((b) => b.textContent.trim() === "Review").click();
    chip("Yes — she's family").click();
    chip("Something else — I'll say it").click();
    setInput("She's my mum's cousin on Fern's side.");
    document.querySelector(".chat-bar .btn-primary").click();
    await new Promise((r) => setTimeout(r, 0));
    const relateCall = fetch.mock.calls.find(([url]) => url === "/api/review/relate");
    expect(JSON.parse(relateCall[1].body)).toEqual({ person_id: "p-judith", text: "She's my mum's cousin on Fern's side." });
    const confirmCall = fetch.mock.calls.find(([url]) => url === "/api/people/confirm");
    expect(JSON.parse(confirmCall[1].body).relation).toContain("first cousin once removed");
    expect(state.people[0].relation).toContain("first cousin once removed"); // the resolved term is on the record
  });
});
