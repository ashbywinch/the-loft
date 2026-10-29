import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../../views/identify.js";
import { documentsToIdentify } from "../../views/home.js";

const STATE = {
  items: [
    {
      id: "doc-1971-05-01",
      type: "document",
      title: "A letter from Fern",
      date: "1971-05-01",
      transcription: "Dear Fern, we swam at Seascale.",
      people: [],
      places: [],
    },
  ],
  people: [{ id: "p-fern", name: "Fern", aliases: ["mamie"] }],
  places: [],
  byId: new Map(),
};

const IDENTIFIED_ITEM = {
  ...STATE.items[0],
  identified: true,
  people: [{ id: "p-fern", status: "proposed" }],
  places: [{ id: "pl-seascale", status: "proposed" }],
};

const SEASCALE = {
  id: "pl-seascale",
  name: "Seascale",
  status: "proposed",
  note: "Mentioned in A letter from Fern — location unknown.",
  basis: { text: "we swam at Seascale", by: "the document", when: "1971-05-01" },
};

beforeEach(() => {
  vi.unstubAllGlobals();
  vi.useFakeTimers();
});

afterEach(async () => {
  // the view's identify call is fire-and-forget: drain until a full
  // macrotask passes with no new fetch call (condition-based, never a tick
  // count) so a chain cannot land on the next test's mock
  try {
    for (let i = 0; i < 20; i++) {
      const before = fetch?.mock?.calls?.length ?? 0;
      await vi.advanceTimersByTimeAsync(0);
      if ((fetch?.mock?.calls?.length ?? 0) === before) return;
    }
    throw new Error("the identification view did not settle — a fetch chain is still in flight");
  } finally {
    vi.useRealTimers();
  }
});

const tick = () => vi.advanceTimersByTimeAsync(0);
// each test gets its own copy: the view mutates the loaded state (a decision
// updates the mention), so a shared fixture would leak decisions forward
const freshState = () => copy(STATE);
const copy = (value) => JSON.parse(JSON.stringify(value));
const buttons = (main) => [...main.querySelectorAll(".identify-entity .btn, .identify-entity .btn-primary")];
const button = (main, label) => buttons(main).find((node) => node.textContent === label);
const decideCall = () => fetch.mock.calls.find(([url]) => url === "/api/identify/decide");

/** The identify route answers the identified document; the decide route
 *  echoes the entity back with the decision's status. */
function stubFetch({ identified = IDENTIFIED_ITEM, places = [SEASCALE] } = {}) {
  const state = freshState();
  vi.stubGlobal(
    "fetch",
    vi.fn((url, init) => {
      if (url.startsWith("/api/identify/document/")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ ok: true, item: copy(identified), people: copy(state.people), places: copy(places), pending: 2 }),
        });
      }
      const body = JSON.parse(init?.body ?? "{}");
      if (body.decision === "delete") {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            ok: true,
            kind: body.kind,
            entity: { id: body.entity_id, gone: true },
            message: "Done — Seascale is not recorded after all.",
            pending: 1,
          }),
        });
      }
      const record = body.kind === "place" ? copy(SEASCALE) : copy(state.people[0]);
      if (body.decision === "attested") delete record.status;
      if (body.decision === "estimated") record.status = "estimated";
      return Promise.resolve({
        ok: true,
        json: async () => ({ ok: true, kind: body.kind, entity: record, message: "Done.", pending: 1 }),
      });
    }),
  );
}

describe("the identification review — one document's people and places", () => {
  it("reads the document once and lists its entities with their evidence", async () => {
    stubFetch();
    const main = document.createElement("main");
    render(main, { arg: "doc-1971-05-01" }, freshState());
    await tick();

    const identify = fetch.mock.calls.filter(([url]) => url.startsWith("/api/identify/document/"));
    expect(identify).toHaveLength(1);
    const rows = [...main.querySelectorAll(".identify-entity")];
    expect(rows.map((row) => row.querySelector(".identify-name").textContent)).toEqual(["Fern", "Seascale"]);
    expect(rows[1].textContent).toContain('It says: "we swam at Seascale"');
    expect(main.querySelector(".identify-text pre").textContent).toBe("Dear Fern, we swam at Seascale.");
    expect(buttons(main).map((node) => node.textContent)).toEqual([
      "Record as a fact",
      "Record as a guess",
      "Leave for later",
      "Delete",
      "Record as a fact",
      "Record as a guess",
      "Leave for later",
      "Delete",
    ]);
  });

  it("record as a fact confirms the mention and the record", async () => {
    stubFetch();
    const main = document.createElement("main");
    render(main, { arg: "doc-1971-05-01" }, freshState());
    await tick();

    button(main, "Record as a fact").click();
    await tick();

    const call = decideCall();
    expect(JSON.parse(call[1].body)).toEqual({
      item_id: "doc-1971-05-01",
      kind: "person",
      entity_id: "p-fern",
      decision: "attested",
      basis: null,
    });
    const rows = [...main.querySelectorAll(".identify-entity")];
    expect(rows[0].textContent).toContain("Recorded as a fact.");
    expect(rows[0].querySelector(".btn")).toBeNull(); // a settled mention is not asked again
  });

  it("record as a guess records the family's own words", async () => {
    stubFetch();
    const main = document.createElement("main");
    render(main, { arg: "doc-1971-05-01" }, freshState());
    await tick();

    button(main, "Record as a guess").click();
    const words = main.querySelector(".identify-entity .field");
    words.value = "we spent every summer there";
    main.querySelector(".identify-guess .btn-primary").click(); // the guess's save button
    await tick();

    const body = JSON.parse(decideCall()[1].body);
    expect(body.decision).toBe("estimated");
    expect(body.basis.text).toBe("we spent every summer there");
    expect(body.basis.by).toBe("the reviewer"); // no signed-in name in this state
    expect(body.basis.when).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("delete removes the mention and the proposal", async () => {
    stubFetch();
    const main = document.createElement("main");
    render(main, { arg: "doc-1971-05-01" }, freshState());
    await tick();

    const deleteButtons = buttons(main).filter((node) => node.textContent === "Delete");
    deleteButtons[1].click(); // Seascale
    await tick();

    const body = JSON.parse(decideCall()[1].body);
    expect(body).toMatchObject({ kind: "place", entity_id: "pl-seascale", decision: "delete" });
    const names = [...main.querySelectorAll(".identify-name")].map((node) => node.textContent);
    expect(names).toEqual(["Fern"]); // the place's mention and record are gone
  });

  it("leave for later keeps the mention proposed but does not re-ask it in this visit", async () => {
    stubFetch();
    const main = document.createElement("main");
    render(main, { arg: "doc-1971-05-01" }, freshState());
    await tick();

    button(main, "Leave for later").click();
    await tick();

    expect(JSON.parse(decideCall()[1].body).decision).toBe("pending");
    const rows = [...main.querySelectorAll(".identify-entity")];
    expect(rows[0].textContent).toContain("Left for later.");
    expect(rows[0].querySelector(".btn")).toBeNull();
  });

  it("an unknown document is not found", () => {
    const main = document.createElement("main");
    render(main, { arg: "doc-1900-01-01" }, freshState());
    expect(main.textContent).toContain("Not found.");
    expect(fetch?.mock?.calls?.length ?? 0).toBe(0);
  });
});

describe("the identification door (UR2)", () => {
  const documentItem = (fields) => ({
    id: "doc-1971-05-01",
    type: "document",
    transcription: "Dear Fern,",
    people: [],
    places: [],
    ...fields,
  });

  it("counts a document the pass has not read", () => {
    const door = documentsToIdentify({ items: [documentItem({})] });
    expect(door).toEqual({ count: 1, href: "#/identify/doc-1971-05-01" });
  });

  it("counts a read document whose mentions still wait", () => {
    const door = documentsToIdentify({
      items: [documentItem({ identified: true, people: [{ id: "p-fern", status: "proposed" }] })],
    });
    expect(door).toEqual({ count: 1, href: "#/identify/doc-1971-05-01" });
  });

  it("is settled when every mention is decided", () => {
    const door = documentsToIdentify({
      items: [
        documentItem({
          identified: true,
          people: [{ id: "p-fern", status: "confirmed" }],
          places: [{ id: "pl-seascale", status: "estimated" }],
        }),
      ],
    });
    expect(door).toBeNull();
  });

  it("never routes to an item with no agreed transcription", () => {
    expect(documentsToIdentify({ items: [documentItem({ type: "photo", transcription: "" })] })).toBeNull();
    expect(documentsToIdentify({ items: [] })).toBeNull();
  });
});
