import { describe, expect, it, beforeEach, vi } from "vitest";
import {
  bandAnchor,
  bandMargin,
  boxToDisplay,
  clearEdits,
  correctedDocumentText,
  correctedPageText,
  displayFrame,
  fitRect,
  flaggedByPage,
  flaggedCount,
  flaggedPositions,
  formatParts,
  lineIndexForY,
  loadEdits,
  nextFlagged,
  outboxAdd,
  outboxDrop,
  outboxPending,
  desiredQuarters,
  pendingRotationQuarters,
  render,
  rotateDrop,
  rotatePending,
  rotateUpsert,
  saveEdits,
  strikeParts,
  zoomView,
} from "../../views/review.js";

/** One reviewable document: two pages, page 1 with a layout (two lines,
 *  three flagged words), page 2 with a layout (no flags). */
const DOC = {
  batch_id: "adopt-1",
  pages: ["p1.jpg", "p2.jpg"],
  texts: { "p1.jpg": "line one\nline two", "p2.jpg": "line three" },
  layouts: {
    "p1.jpg": {
      page: "p1.jpg",
      width: 100,
      height: 100,
      lines: [
        {
          index: 0,
          text: "line one",
          box: [0, 0, 10, 10],
          conf: 0.5,
          words: [
            { word: "line", box: null, conf: 1 },
            { word: "one", box: null, conf: 0 },
          ],
        },
        {
          index: 1,
          text: "line two",
          box: null,
          conf: 0,
          words: [
            { word: "line", box: null, conf: 0 },
            { word: "two", box: null, conf: 0 },
          ],
        },
      ],
      unmatched: [],
    },
    "p2.jpg": {
      page: "p2.jpg",
      width: 100,
      height: 100,
      lines: [
        {
          index: 0,
          text: "line three",
          box: [0, 0, 5, 5],
          conf: 1,
          words: [
            { word: "line", box: null, conf: 1 },
            { word: "three", box: null, conf: 1 },
          ],
        },
      ],
      unmatched: [],
    },
  },
  status: "review",
};

describe("flaggedCount — the lines still to check", () => {
  it("counts flagged LINES (a line once, however many of its words are flagged); edited lines excluded", () => {
    expect(flaggedCount([DOC], 0, {})).toBe(2);
    expect(flaggedCount([DOC], 0, { "p1.jpg": { 1: "line two — verified" } })).toBe(1);
    expect(flaggedCount([DOC], 0, { "p1.jpg": { 0: "x", 1: "y" } })).toBe(0);
  });

  it("pages without a layout contribute nothing", () => {
    const doc = { ...DOC, layouts: {} };
    expect(flaggedCount([doc], 0, {})).toBe(0);
  });
});

describe("flaggedByPage — the navigation strip's flag dots", () => {
  it("groups the remaining flagged lines per page (2026-08-16: the dots make a cross-page Next-flagged jump visible)", () => {
    expect(flaggedByPage([DOC], 0, {})).toEqual({ "p1.jpg": 2 });
    expect(flaggedByPage([DOC], 0, { "p1.jpg": { 1: "done" } })).toEqual({ "p1.jpg": 1 });
    expect(flaggedByPage([DOC], 0, { "p1.jpg": { 0: "a", 1: "b" } })).toEqual({});
  });

  it("a document with no flags has no dots", () => {
    const doc = { ...DOC, layouts: { "p1.jpg": { ...DOC.layouts["p1.jpg"], lines: [] } } };
    expect(flaggedByPage([doc], 0, {})).toEqual({});
  });
});

describe("corrected text — the confirmation payload", () => {
  it("applies the reviewer's edits to the layout's verbatim lines", () => {
    expect(correctedPageText(DOC, "p1.jpg", { "p1.jpg": { 0: "LINE ONE" } })).toBe("LINE ONE\nline two");
    expect(correctedPageText(DOC, "p1.jpg", {})).toBe("line one\nline two");
  });

  it("a page with no layout is its raw guess text", () => {
    const doc = { ...DOC, layouts: {} };
    expect(correctedPageText(doc, "p1.jpg", {})).toBe("line one\nline two");
  });

  it("the document text joins pages with newlines (the CLI gate's shape)", () => {
    expect(correctedDocumentText(DOC, {})).toBe("line one\nline two\nline three");
    expect(correctedDocumentText(DOC, { "p1.jpg": { 0: "LINE ONE" } })).toBe(
      "LINE ONE\nline two\nline three",
    );
  });
});

describe("flag navigation — bounded and resumable (VR9)", () => {
  it("lists flagged LINES in reading order across pages, one entry per line", () => {
    expect(flaggedPositions([DOC], 0, {})).toEqual([
      { page: "p1.jpg", line: 0 },
      { page: "p1.jpg", line: 1 },
    ]);
  });

  it("edits remove the line's position", () => {
    expect(flaggedPositions([DOC], 0, { "p1.jpg": { 1: "done" } })).toEqual([
      { page: "p1.jpg", line: 0 },
    ]);
  });

  it("nextFlagged walks forward and wraps; null with nothing left", () => {
    const positions = flaggedPositions([DOC], 0, {});
    expect(nextFlagged(positions, null)).toEqual(positions[0]);
    expect(nextFlagged(positions, positions[0])).toEqual(positions[1]);
    expect(nextFlagged(positions, positions[1])).toEqual(positions[0]);
    expect(nextFlagged([], null)).toBeNull();
  });

  it("nextFlagged continues AFTER an accepted position instead of restarting", () => {
    // the from's line was accepted (removed from the list) — the tour
    // must continue after it by order, not blink back at the first flag
    const positions = [
      { page: "page-03.jpg", line: 0 },
      { page: "page-03.jpg", line: 1 },
      { page: "page-04.jpg", line: 2 },
    ];
    expect(nextFlagged(positions, { page: "page-03.jpg", line: 0 })).toEqual(positions[1]);
    expect(nextFlagged(positions, { page: "page-03.jpg", line: 1 })).toEqual(positions[2]);
    // the from on a fully-accepted page — continue on the next page
    expect(nextFlagged(positions, { page: "page-03.jpg", line: 9 })).toEqual(positions[2]);
    // the from was the LAST position (accepted) — wrap to the start
    expect(nextFlagged(positions, { page: "page-04.jpg", line: 2 })).toEqual(positions[0]);
  });
});

describe("the outbox — nothing confirmed is lost to a failed push", () => {
  beforeEach(() => localStorage.clear());

  it("adds, lists, and drops payloads", () => {
    const payload = { batch_id: "b", doc_index: 1, status: "confirmed" };
    expect(outboxPending()).toEqual([]);
    outboxAdd(payload);
    expect(outboxPending()).toEqual([payload]);
    outboxDrop(payload);
    expect(outboxPending()).toEqual([]);
  });

  it("survives a malformed store (returns empty, never throws)", () => {
    localStorage.setItem("loft-review-outbox", "{not json");
    expect(outboxPending()).toEqual([]);
  });
});

describe("the reviewer's edits persist — resumable, VR9", () => {
  beforeEach(() => localStorage.clear());

  it("saves, restores, and clears per (batch, document)", () => {
    expect(loadEdits("b1", 2)).toEqual({});
    saveEdits("b1", 2, { "p1.jpg": { 0: "fixed line" } });
    expect(loadEdits("b1", 2)).toEqual({ "p1.jpg": { 0: "fixed line" } });
    // other documents and batches are untouched
    expect(loadEdits("b1", 3)).toEqual({});
    expect(loadEdits("b2", 2)).toEqual({});
    clearEdits("b1", 2);
    expect(loadEdits("b1", 2)).toEqual({});
  });

  it("survives a malformed store", () => {
    localStorage.setItem("loft-review-edits", "{nope");
    expect(loadEdits("b1", 0)).toEqual({});
  });
});

describe("formatParts — the strike and underline conventions (2026-08-16)", () => {
  it("splits ~~struck~~ and ~underlined~ into their kinds", () => {
    expect(formatParts("a ~~crossed out~~ and ~underlined~ word")).toEqual([
      { text: "a ", kind: null },
      { text: "crossed out", kind: "struck" },
      { text: " and ", kind: null },
      { text: "underlined", kind: "underlined" },
      { text: " word", kind: null },
    ]);
  });

  it("strikeParts keeps the struck flag only (an underline is stripped, not struck)", () => {
    expect(strikeParts("~underlined~")).toEqual([{ text: "underlined", struck: false }]);
    expect(strikeParts("~~reading~~")).toEqual([{ text: "reading", struck: true }]);
  });
});

describe("strikethrough rendering — the VLM's ~~struck~~ words", () => {
  it("splits a token into struck and plain parts", () => {
    expect(strikeParts("~~reading~~")).toEqual([{ text: "reading", struck: true }]);
    expect(strikeParts("a single ~~reading~~ lamp")).toEqual([
      { text: "a single ", struck: false },
      { text: "reading", struck: true },
      { text: " lamp", struck: false },
    ]);
  });

  it("leaves plain tokens untouched", () => {
    expect(strikeParts("ordinary")).toEqual([{ text: "ordinary", struck: false }]);
  });
});

describe("the batch list renders the real batches", () => {
  beforeEach(() => localStorage.clear());

  it("shows the open batches and hides confirmed ones", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          batches: [
            { batch_id: "b-open", label: "First pile", status: "review", pages: { a: 1, b: 2 }, boundaries: [{ pages: ["a"], status: null }] },
            { batch_id: "b-done", label: "Old pile", status: "confirmed", pages: {}, boundaries: [{ pages: ["a"], status: "confirmed" }] },
          ],
        }),
      }),
    );
    const main = document.createElement("main");
    render(main, { name: "review" });
    await vi.waitFor(() => expect(main.textContent).toContain("First pile"));
    expect(main.textContent).toContain("0 of 1 confirmed");
    expect(main.textContent).not.toContain("Old pile");
    expect(main.textContent).not.toContain("No batches");
    vi.unstubAllGlobals();
  });

  it("offers the sign-in gate on a 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 401 }),
    );
    const main = document.createElement("main");
    render(main, { name: "review" });
    await vi.waitFor(() => expect(main.querySelector(".gate")).toBeTruthy());
    vi.unstubAllGlobals();
  });
});

describe("the review hub shows both transcriptions and import sessions", () => {
  beforeEach(() => localStorage.clear());

  it("shows import sessions when the state has pending imports", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ batches: [] }),
      }),
    );
    const main = document.createElement("main");
    const state = {
      items: [],
      imports: [{ id: "import-documents", title: "The document import", status: "pending" }],
      people: [{ id: "p-judith", name: "Pearl Whitlock", relation: "cousin", status: "proposed" }],
      me: { person: "p-alex" },
    };
    render(main, { name: "review" }, state);
    await vi.waitFor(() => expect(main.textContent).toContain("The document import"));
    expect(main.textContent).toContain("1 person");
    // the card is a button that navigates to the import session
    expect(main.querySelector('.rv-card-title')?.textContent).toContain("The document import");
    vi.unstubAllGlobals();
  });
});

describe("the plain-image viewer geometry (2026-08-16: OpenSeadragon replaced)", () => {
  it("bandAnchor: the first line box anchors the band", () => {
    const layout = {
      lines: [
        { box: [100, 500, 900, 600] },
        { box: [50, 700, 800, 780] },
      ],
    };
    expect(bandAnchor(layout)).toBe(500);
  });

  it("bandAnchor: a boxless page falls back to the detector's first unmatched line", () => {
    const layout = {
      lines: [{ box: null }, { box: null }],
      unmatched: [{ box: [1546, 961, 1847, 1052] }, { box: [689, 998, 1824, 1194] }],
    };
    expect(bandAnchor(layout)).toBe(961);
  });

  it("bandAnchor: nothing known anchors at 0", () => {
    expect(bandAnchor({ lines: [] })).toBe(0);
    expect(bandAnchor({ lines: [{ box: null }], unmatched: [] })).toBe(0);
    expect(bandAnchor(null)).toBe(0);
  });

  it("bandMargin: half the TOPMOST box's height — the rec's boxes sit below the ink", () => {
    const layout = {
      lines: [
        // the reading-first line whose box is a mid-page fragment (page-05)
        { box: [0, 2611, 100, 2697] },
        // the topmost box — the rec's tall merged detection (134px)
        { box: [0, 2385, 100, 2519] },
      ],
    };
    // the margin comes from the TOPMOST box, not the first reading line —
    // the topmost box is what the ink starts near
    expect(bandMargin(layout)).toBe(67);
    expect(bandAnchor(layout)).toBe(2385);
    expect(bandMargin({ lines: [{ box: null }] })).toBe(0);
    expect(bandMargin(null)).toBe(0);
  });

  it("displayFrame is the identity at rot 0", () => {
    const f = displayFrame(0, 2544, 4642);
    expect(f).toEqual({ a: 1, b: 0, c: 0, d: 1, ox: 0, oy: 0, dw: 2544, dh: 4642 });
  });

  it("rot 90 swaps the dims and maps the original bottom-left to display (0,0)", () => {
    const f = displayFrame(90, 2544, 4642);
    expect([f.dw, f.dh]).toEqual([4642, 2544]);
    // original (x, y) → display (-y + h, x)
    expect(boxToDisplay(f, [0, 4632, 10, 4642])).toEqual({ x: 0, y: 0, width: 10, height: 10 });
  });

  it("rot 180 flips both axes; rot 270 maps the original top-right to display (0,0)", () => {
    const f180 = displayFrame(180, 100, 200);
    expect([f180.dw, f180.dh]).toEqual([100, 200]);
    expect(boxToDisplay(f180, [0, 0, 10, 10])).toEqual({ x: 90, y: 190, width: 10, height: 10 });
    const f270 = displayFrame(270, 100, 200);
    expect([f270.dw, f270.dh]).toEqual([200, 100]);
    expect(boxToDisplay(f270, [90, 0, 100, 10])).toEqual({ x: 0, y: 0, width: 10, height: 10 });
  });

  it("fitRect: the phone's band — the page fills the pane width, anchored at the writing", () => {
    // 812×131 phone pane; the 2544-wide page; the visible band is 2544×410
    const view = fitRect(812, 131, { x: 0, y: 2251, width: 2544, height: 410 });
    expect(view.x).toBe(0);
    expect(view.y).toBe(2251);
    expect(view.width).toBe(2544);
    expect(view.height).toBeCloseTo(2544 / (812 / 131), 5);
  });

  it("fitRect: a tall pane fits the whole page (height rules)", () => {
    const view = fitRect(600, 700, { x: 0, y: 0, width: 2544, height: 4642 });
    expect(view.height).toBe(4642);
    expect(view.width).toBeCloseTo(4642 * (600 / 700), 5);
  });

  it("fitRect: zoom-to-line fills the pane with the line", () => {
    // "Our week includes:" — box [597, 2338, 1066, 2417] (469×79); its
    // aspect (5.9) is slightly narrower than the pane's (6.2) → height-fit
    const view = fitRect(812, 131, { x: 0, y: 2338, width: 469, height: 79 });
    expect(view.height).toBe(79);
    expect(view.width).toBeCloseTo(79 * (812 / 131), 5);
  });

  it("zoomView: the image point under the cursor stays put when zooming", () => {
    const paneW = 812, paneH = 131;
    const before = { x: 0, y: 100, width: 2544, height: 410 };
    const k = 2;
    const cx = paneW / 2, cy = paneH / 2;
    const after = zoomView(before, k, paneW, paneH, cx, cy, 2544);
    // the pane-center image point before and after
    const s = paneW / before.width;
    const ix = before.x + cx / s;
    const iy = before.y + cy / s;
    const s2 = paneW / after.width;
    expect(after.x + cx / s2).toBeCloseTo(ix, 6);
    expect(after.y + cy / s2).toBeCloseTo(iy, 6);
    expect(after.width).toBeCloseTo(before.width / k, 6);
  });

  it("zoomView clamps to [1/8, 8]× the image width", () => {
    const paneW = 812, paneH = 131;
    const wide = zoomView({ x: 0, y: 0, width: 2544, height: 410 }, 100, paneW, paneH, 0, 0, 2544);
    expect(wide.width).toBe(2544 / 8);
    const deep = zoomView({ x: 0, y: 0, width: 2544, height: 410 }, 0.0001, paneW, paneH, 0, 0, 2544);
    expect(deep.width).toBe(2544 * 8);
  });
});

describe("the rotation outbox — the orientation fix survives an offline backend", () => {
  beforeEach(() => localStorage.clear());

  it("upserts one intent per page — the latest wins (multiple presses coalesce, 2026-08-16)", () => {
    rotateUpsert("adopt-1", "p1.jpg", 2);
    rotateUpsert("adopt-1", "p1.jpg", 3);
    expect(rotatePending()).toEqual([{ batch_id: "adopt-1", page: "p1.jpg", quarters: 3 }]);
    expect(pendingRotationQuarters("adopt-1", "p1.jpg")).toBe(3);
  });

  it("different pages keep their own intents", () => {
    rotateUpsert("adopt-1", "p1.jpg", 1);
    rotateUpsert("adopt-1", "p2.jpg", 2);
    expect(rotatePending().length).toBe(2);
    expect(pendingRotationQuarters("adopt-1", "p1.jpg")).toBe(1);
    expect(pendingRotationQuarters("adopt-1", "p2.jpg")).toBe(2);
  });

  it("drops the intent once the backend records it", () => {
    rotateUpsert("adopt-1", "p1.jpg", 1);
    rotateDrop("adopt-1", "p1.jpg");
    expect(rotatePending()).toEqual([]);
    expect(pendingRotationQuarters("adopt-1", "p1.jpg")).toBe(0);
  });

  it("desiredQuarters: the rotate-back to the ORIGINAL is a real 0 intent", () => {
    // a reviewer over-correcting an already-rotated page: the layout is at
    // 90 and the view is rotated -90 — the desired is 0, which the backend
    // must receive (bot review, 2026-08-16: dropping it left the page
    // wrongly rotated and the confirm blocked)
    expect(desiredQuarters(90, -90)).toBe(0);
    expect(desiredQuarters(0, 90)).toBe(1);
    expect(desiredQuarters(90, 180)).toBe(3);
    expect(desiredQuarters(270, 90)).toBe(0);
  });
});

describe("the dual-pane link — the image-y to line mapping (2026-08-16)", () => {
  const LAYOUT = {
    lines: [
      { index: 0, box: [0, 100, 100, 120] },
      { index: 1, box: [0, 200, 100, 220] },
      { index: 2, box: [0, 300, 100, 320] },
    ],
  };

  it("finds the line whose box contains the image y", () => {
    expect(lineIndexForY(LAYOUT, 0, { w: 100, h: 400 }, 110)).toBe(0);
    expect(lineIndexForY(LAYOUT, 0, { w: 100, h: 400 }, 210)).toBe(1);
  });

  it("falls to the first line below when y is in a gap", () => {
    const gapLayout = { lines: [LAYOUT.lines[0], LAYOUT.lines[2]] };
    expect(lineIndexForY(gapLayout, 0, { w: 100, h: 400 }, 150)).toBe(2);
    expect(lineIndexForY(gapLayout, 0, { w: 100, h: 400 }, 50)).toBe(0);
  });

  it("maps through the rotation's display frame", () => {
    // rot 90: the box [0,100,100,120] in a 100x400 image -> display
    // [400-120, 0, 400-100, 100] = [280, 0, 20, 100] — its display y 0..100
    expect(lineIndexForY(LAYOUT, 90, { w: 100, h: 400 }, 50)).toBe(0);
  });

  it("a box-less layout maps to nothing", () => {
    expect(lineIndexForY({ lines: [{ index: 0, box: null }] }, 0, { w: 100, h: 400 }, 50)).toBeNull();
  });
});

describe("marking a line fine — the verbatim text counts as verified", () => {
  it("the edit = the line's own text clears its flags (applyMarkedFine's mechanism, 2026-08-16)", () => {
    expect(flaggedCount([DOC], 0, { "p1.jpg": { 0: "line one" } })).toBe(1);
    expect(flaggedCount([DOC], 0, { "p1.jpg": { 0: "line one", 1: "line two" } })).toBe(0);
    // the corrected document text keeps the verbatim line unchanged
    expect(correctedDocumentText(DOC, { "p1.jpg": { 0: "line one" } })).toBe("line one\nline two\nline three");
  });
});

describe("the document list shows only awaiting documents (user 2026-08-16)", () => {
  beforeEach(() => localStorage.clear());

  it("a confirmed document is not listed — the list is the work still to do", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          batch_id: "adopt-1",
          label: "Pile",
          documents: [
            { ...DOC, status: "review", pages: ["p1.jpg"] },
            { ...DOC, status: "confirmed", pages: ["p2.jpg"] },
          ],
        }),
      }),
    );
    const main = document.createElement("main");
    render(main, { name: "review", arg: "adopt-1", rest: ["review", "adopt-1"] });
    await vi.waitFor(() => expect(main.textContent).toContain("Document 1 of 1"));
    expect(main.textContent).not.toContain("Confirmed");
    vi.unstubAllGlobals();
  });

  it("a fully confirmed batch shows the all-done note, not cards", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          batch_id: "adopt-1",
          label: "Pile",
          documents: [{ ...DOC, status: "confirmed", pages: ["p2.jpg"] }],
        }),
      }),
    );
    const main = document.createElement("main");
    render(main, { name: "review", arg: "adopt-1", rest: ["review", "adopt-1"] });
    await vi.waitFor(() => expect(main.textContent).toContain("confirmed."));
    expect(main.querySelectorAll(".rv-card").length).toBe(0);
    vi.unstubAllGlobals();
  });
});
