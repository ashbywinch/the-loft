import { describe, expect, it } from "vitest";
import { render } from "../../views/import.js";

const STATE = {
  imports: [{ id: "import-documents", title: "The document import", status: "pending" }],
  people: [{ id: "p-judith", name: "Pearl Whitlock", relation: "cousin — researcher", status: "proposed" }],
  relationships: [],
};

describe("the import review (2026-08-07, user: the session's pending people are confirmed here)", () => {
  it("lists the session's pending people with confirm and dismiss", () => {
    const main = document.createElement("main");
    render(main, { arg: "import-documents", query: new URLSearchParams() }, STATE);
    expect(main.textContent).toContain("The document import");
    expect(main.textContent).toContain("Pearl Whitlock");
    const buttons = [...main.querySelectorAll("button")].map((b) => b.textContent.trim());
    expect(buttons).toContain("Confirm");
    expect(buttons).toContain("Dismiss");
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

describe("the session completes client-side (2026-08-07 review: no reload needed)", () => {
  it("confirming the last pending person flips the session to reviewed in state", async () => {
    const { vi } = await import("vitest");
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: async () => ({ ok: true, person: { id: "p-judith", name: "Pearl Whitlock", relation: "cousin" } }),
        }),
      ),
    );
    const main = document.createElement("main");
    const state = JSON.parse(JSON.stringify(STATE));
    render(main, { arg: "import-documents", query: new URLSearchParams() }, state);
    [...main.querySelectorAll("button")].find((b) => b.textContent.trim() === "Confirm").click();
    await new Promise((r) => setTimeout(r, 0));
    expect(state.imports[0].status).toBe("reviewed"); // nothing pending — the card leaves the front page
  });
});
