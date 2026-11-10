import { describe, expect, it, afterEach, vi } from "vitest";
import { paintTints, render, rowsRect, strokeLength, tintPath } from "../../views/rows.js";

/** One page's two tints, as the drafts payload carries them: the colour and
 *  the rectangles the pipeline draws (no formula is re-derived here). */
const TINTS = [
  {
    colour: [242, 92, 92, 55],
    rects: [
      { x0: 100, y0: 200, x1: 300, y1: 260 },
      { x0: 300, y0: 210, x1: 460, y1: 270 },
    ],
  },
  {
    colour: [92, 242, 92, 55],
    rects: [{ x0: 100, y0: 300, x1: 460, y1: 360 }],
  },
];

const DRAFTS = {
  batch_id: "b1",
  documents: [
    {
      pages: ["p1.jpg", "p2.jpg"],
      texts: { "p1.jpg": "one", "p2.jpg": "two" },
      layouts: {},
      tints: { "p1.jpg": TINTS },
      row_adjustments: {},
      adjusted_rows: {},
    },
  ],
};

function stubFetch(answer = DRAFTS) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) => {
      if (String(url).includes("/row-adjustments")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ok: true, rows: [], violations: [], tints: [TINTS[0]] }),
        };
      }
      return { ok: true, status: 200, json: async () => answer };
    }),
  );
}

async function openPage() {
  const main = document.createElement("main");
  render(main, { arg: "b1", rest: ["rows", "b1", "0", "0"] }, {});
  await vi.waitFor(() => expect(main.querySelector(".rv-page")).toBeTruthy());
  const img = main.querySelector(".rv-page");
  Object.defineProperty(img, "naturalWidth", { value: 600, configurable: true });
  Object.defineProperty(img, "naturalHeight", { value: 800, configurable: true });
  const box = main.querySelector(".rv-imgbox");
  Object.defineProperty(box, "clientWidth", { value: 390, configurable: true });
  Object.defineProperty(box, "clientHeight", { value: 700, configurable: true });
  img.dispatchEvent(new Event("load"));
  return { main, img, box };
}

describe("the row review's tints — the pipeline's records, painted", () => {
  it("paints one path per row, filled and faded by the record", () => {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    paintTints(group, TINTS);
    const paths = Array.from(group.children);
    expect(paths).toHaveLength(2);
    expect(paths[0].getAttribute("fill")).toBe("rgb(242 92 92)");
    expect(Number(paths[0].getAttribute("fill-opacity"))).toBeCloseTo(55 / 255, 6);
    expect(paths[1].getAttribute("fill")).toBe("rgb(92 242 92)");
  });

  it("one row is ONE path: its rectangles are subpaths, so overlaps fill once", () => {
    const d = tintPath(TINTS[0].rects);
    expect(d).toBe("M100 200H300V260H100ZM300 210H460V270H300Z");
  });

  it("the fit rect is the writing's union, not the page", () => {
    expect(rowsRect(TINTS)).toEqual({ x: 100, y: 200, width: 360, height: 160 });
    expect(rowsRect([])).toBeNull();
  });

  it("a stroke's length tells a line from a tap", () => {
    expect(
      strokeLength([
        { x: 0, y: 0 },
        { x: 30, y: 0 },
      ]),
    ).toBe(30);
    expect(strokeLength([{ x: 0, y: 0 }])).toBe(0);
  });
});

describe("the row review screen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("paints a loading state while the drafts are loading", async () => {
    let resolveFetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise((resolve) => {
            resolveFetch = resolve;
          }),
      ),
    );
    const main = document.createElement("main");
    render(main, { arg: "b1", rest: ["rows", "b1", "0", "0"] }, {});
    expect(main.textContent).toContain("Loading the page");
    resolveFetch({ ok: true, status: 200, json: async () => DRAFTS });
    await vi.waitFor(() => expect(main.querySelector(".rv-page")).toBeTruthy());
  });

  it("paints the machine's rows before anything is drawn", async () => {
    stubFetch();
    const { main } = await openPage();
    const paths = main.querySelectorAll(".rv-tint path");
    expect(paths).toHaveLength(2);
    expect(main.querySelector(".rv-rowbar .rv-btn--primary").textContent).toBe("Rows are right");
    expect(main.querySelector(".rv-rowtools")).toBeNull(); // no toolbar on the page
  });

  it("a drawn line posts the whole normalised set and repaints the answer's tints", async () => {
    stubFetch();
    const { main, box } = await openPage();
    box.dispatchEvent(
      new PointerEvent("pointerdown", { pointerId: 1, clientX: 60, clientY: 300, pointerType: "touch" }),
    );
    window.dispatchEvent(
      new PointerEvent("pointermove", { pointerId: 1, clientX: 60, clientY: 320, pointerType: "touch" }),
    );
    window.dispatchEvent(
      new PointerEvent("pointermove", { pointerId: 1, clientX: 300, clientY: 320, pointerType: "touch" }),
    );
    window.dispatchEvent(
      new PointerEvent("pointerup", { pointerId: 1, clientX: 300, clientY: 320, pointerType: "touch" }),
    );
    await vi.waitFor(() => {
      const posted = fetch.mock.calls.find(([url]) => String(url).includes("/row-adjustments"));
      expect(posted).toBeTruthy();
    });
    const posted = fetch.mock.calls.find(([url]) => String(url).includes("/row-adjustments"));
    const body = JSON.parse(posted[1].body);
    expect(body.lines).toHaveLength(1);
    expect(body.lines[0].length).toBeGreaterThan(1);
    for (const [x, y] of body.lines[0]) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(1);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(1);
    }
    // the answer's tints replace the painted rows
    await vi.waitFor(() => expect(main.querySelectorAll(".rv-tint path")).toHaveLength(1));
  });

  it("the finish records the page and opens the next page whose rows wait", async () => {
    stubFetch();
    const { main } = await openPage();
    main.querySelector(".rv-rowbar .rv-btn--primary").click();
    await vi.waitFor(() => expect(location.hash).toBe("#/rows/b1/0/1"));
    // nothing was drawn, so nothing was posted: the check is the record
    expect(fetch.mock.calls.some(([url]) => String(url).includes("/row-adjustments"))).toBe(false);
  });

  it("a tap on a drawn line removes it", async () => {
    stubFetch();
    const { main, box } = await openPage();
    // one finger, one short tap: no stroke, so the line it lands on goes
    const draw = (from, to) => {
      box.dispatchEvent(
        new PointerEvent("pointerdown", { pointerId: 1, clientX: from, clientY: 300, pointerType: "touch" }),
      );
      window.dispatchEvent(
        new PointerEvent("pointermove", { pointerId: 1, clientX: to, clientY: 300, pointerType: "touch" }),
      );
      window.dispatchEvent(
        new PointerEvent("pointerup", { pointerId: 1, clientX: to, clientY: 300, pointerType: "touch" }),
      );
    };
    draw(60, 300);
    await vi.waitFor(() => expect(main.querySelectorAll(".rv-stroke")).toHaveLength(1));
    draw(200, 200);
    await vi.waitFor(() => {
      const posted = fetch.mock.calls.filter(([url]) => String(url).includes("/row-adjustments"));
      expect(JSON.parse(posted.at(-1)[1].body).lines).toHaveLength(0);
    });
  });
});
