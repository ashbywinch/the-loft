import { describe, expect, it } from "vitest";
import { buildFallbackMap, heatStepForZoom, placePage, render, scaleState } from "../../views/places.js";

describe("places fallback map", () => {
  const places = [
    { id: "a", name: "A", x: 10, y: 20 },
    { id: "b", name: "B", x: 30, y: 40 },
  ];

  it("renders one pin per place and a route", () => {
    const svg = buildFallbackMap(
      places,
      new Map([
        ["a", 3],
        ["b", 0],
      ]),
    );
    expect(svg instanceof SVGElement).toBe(true);
    expect(svg.querySelectorAll("circle.map-pin").length).toBe(2);
    expect(svg.querySelector("path.map-route")).toBeTruthy();
  });

  it("wraps active places in links", () => {
    const svg = buildFallbackMap(
      places,
      new Map([
        ["a", 3],
        ["b", 0],
      ]),
      "?from=1961&to=1965",
    );
    const links = svg.querySelectorAll("a.map-dot-link");
    expect(links.length).toBe(1);
    expect(links[0].getAttribute("href")).toBe("#/place/a?from=1961&to=1965");
  });

  it("sizes pins by count", () => {
    const svg = buildFallbackMap(
      places,
      new Map([
        ["a", 10],
        ["b", 0],
      ]),
    );
    const radii = [...svg.querySelectorAll("circle.map-pin")].map((c) => Number(c.getAttribute("r")));
    expect(radii[0]).toBeGreaterThan(radii[1]);
  });

  it("starts the route path with M even when the first route place is missing", () => {
    // Only the second ROUTE place exists — a naive join would emit ' L…' and
    // silently drop the whole path (invalid SVG data).
    const partial = [{ id: "pl-farndale-wharf", name: "Iron Wharf", x: 55, y: 58 }];
    const svg = buildFallbackMap(partial, new Map([["pl-farndale-wharf", 2]]));
    const d = svg.querySelector("path.map-route").getAttribute("d");
    expect(d.startsWith("M")).toBe(true);
    expect(d).not.toContain("L");
  });

  it("skips places without a position — no translate(null) dot, no crash (2026-08-05)", () => {
    // Rule O: unverified coordinates are null in the projection — a dot for a
    // place with no position is meaningless and `translate(null, null)` is
    // invalid SVG that kills the whole Places door.
    const withNulls = [
      { id: "a", name: "A", x: 10, y: 20 },
      { id: "pl-kirkby", name: "Stonewick", x: null, y: null },
    ];
    const svg = buildFallbackMap(withNulls, new Map([["a", 2], ["pl-kirkby", 1]]));
    expect(svg.querySelectorAll("circle.map-pin").length).toBe(1);
    expect(svg.textContent).not.toContain("Stonewick");
    expect(svg.innerHTML).not.toContain("translate(null");
    expect(svg.innerHTML).not.toContain("translate(undefined");
  });

  it("an imprecise place draws an uncertainty ring, not a precise pin (2026-08-05)", () => {
    // The Lark Inn is somewhere in Stonewick — its point is the town
    // centre and the map must say so, not lie with a pin.
    const places = [
      { id: "pl-inn", name: "The Lark Inn", x: 50, y: 50, precision: "town" },
      { id: "pl-house", name: "4 Carlisle Terrace", x: 60, y: 40, precision: "exact" },
    ];
    const svg = buildFallbackMap(places, new Map([["pl-inn", 1], ["pl-house", 1]]));
    const inn = svg.querySelector(".map-ring");
    expect(inn).toBeTruthy();
    const radii = [...svg.querySelectorAll("circle")].map((c) => Number(c.getAttribute("r")));
    expect(radii[0]).toBeGreaterThan(radii[1]); // the ring is bigger than the pin
    expect(places[0].precision).toBe("town");
  });
});

describe("scale-aware markers and heat (2026-08-03)", () => {
  it("heat is tuned per zoom: discrete vivid spots at world scale, smooth backdrop at street scale", () => {
    const world = heatStepForZoom(2);
    const regional = heatStepForZoom(7);
    const street = heatStepForZoom(12);
    const maxed = heatStepForZoom(18); // at/over the top of the last step
    expect(world.radius).toBeLessThan(regional.radius);
    expect(regional.radius).toBeLessThan(street.radius);
    expect(world.minOpacity).toBeGreaterThan(street.minOpacity); // sparse points stay visible when zoomed out
    expect(maxed).toEqual(street);
  });

  it("world scale shows heat only — no dots, no labels", () => {
    expect(scaleState(2, 22)).toEqual({ showDots: false, showLabels: false });
    expect(scaleState(7, 22)).toEqual({ showDots: false, showLabels: false });
  });

  it("regional zoom shows dots, street zoom adds labels", () => {
    expect(scaleState(8, 22)).toEqual({ showDots: true, showLabels: false });
    expect(scaleState(11, 22)).toEqual({ showDots: true, showLabels: false });
    expect(scaleState(12, 22)).toEqual({ showDots: true, showLabels: true });
  });

  it("a lone active place always gets its dot and label", () => {
    expect(scaleState(2, 1)).toEqual({ showDots: true, showLabels: true });
    expect(scaleState(10, 1)).toEqual({ showDots: true, showLabels: true });
  });
});

describe("place grid follows the map filter", () => {
  it("lists only places with items in the current scope (2026-08-03)", () => {
    const state = {
      items: [
        {
          id: "letter-1",
          title: "A letter",
          date: "1963-05-14",
          date_precision: "exact",
          type: "letter",
          people: [],
          places: [{ id: "pl-a" }],
          themes: [],
        },
      ],
      people: [],
      places: [
        { id: "pl-a", name: "A", x: 10, y: 20, note: "has items" },
        { id: "pl-b", name: "B", x: 30, y: 40, note: "no items" },
      ],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, {}, state);
    const cards = [...main.querySelectorAll(".place-card .card-title")].map((c) => c.textContent.trim());
    expect(cards).toContain("A");
    expect(cards).not.toContain("B");
  });

  it("skips malformed dates in the fresh view too (2026-08-03 review)", () => {
    // fresh mode previously counted an undated item's places, but the windowed
    // view and the timeline skip it — views must agree
    const state = {
      items: [
        {
          id: "undated",
          title: "Undated",
          date: "not-a-date",
          date_precision: "year",
          type: "story",
          people: [],
          places: [{ id: "pl-a" }],
          themes: [],
        },
      ],
      people: [],
      places: [{ id: "pl-a", name: "A", x: 10, y: 20, note: "undated item" }],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, {}, state);
    const cards = [...main.querySelectorAll(".place-card .card-title")].map((c) => c.textContent.trim());
    expect(cards).not.toContain("A");
  });

  it("a coordinate-less place still lists in the grid — the door never crashes (2026-08-05)", () => {
    // Rule O nulls unverified coordinates; the map must render without the
    // place while the cards below keep it explorable.
    const state = {
      items: [
        {
          id: "email-1",
          title: "The email",
          date: "2001-02-07",
          date_precision: "exact",
          type: "document",
          people: [],
          places: [{ id: "pl-kirkby" }],
          themes: [],
        },
      ],
      people: [],
      places: [
        { id: "pl-a", name: "A", x: 10, y: 20, note: "has items" },
        { id: "pl-kirkby", name: "Stonewick", x: null, y: null, lat: null, lng: null, note: "verification pending" },
      ],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, {}, state); // must not throw
    const cards = [...main.querySelectorAll(".place-card .card-title")].map((c) => c.textContent.trim());
    expect(cards).toContain("Stonewick");
    expect(main.innerHTML).not.toContain("translate(null");
  });
});

describe("map person chips", () => {
  it("lists only people with a place-linked item — Jude never gets a chip", () => {
    const state = {
      items: [
        {
          id: "letter-1",
          title: "A letter",
          date: "1963-05-14",
          date_precision: "exact",
          type: "letter",
          people: [{ id: "p-mum" }],
          places: [{ id: "pl-aldgate", people: ["p-mum"] }],
          themes: [],
        },
        {
          id: "story-1",
          title: "A testimony",
          date: "2026-06-30",
          date_precision: "exact",
          type: "story",
          people: [{ id: "p-jude" }],
          places: [],
          themes: [],
        },
      ],
      people: [
        { id: "p-mum", name: "Nora Hale" },
        { id: "p-jude", name: "Jude Hale" },
      ],
      places: [{ id: "pl-aldgate", name: "Aldgate", x: 50, y: 60 }],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, {}, state);
    const chips = [...main.querySelectorAll(".chips .chip")].map((c) => c.textContent.trim());
    expect(chips).toContain("Nora Hale");
    expect(chips).not.toContain("Jude Hale");
  });
});

describe("place page timeline link", () => {
  it('keeps the active person filter on the "see all on the timeline" link', () => {
    const items = Array.from({ length: 9 }, (_, i) => ({
      id: `letter-${i}`,
      title: `Letter ${i}`,
      date: `1963-05-${String(i + 1).padStart(2, "0")}`,
      date_precision: "exact",
      type: "letter",
      places: [{ id: "pl-x", people: ["p-mum"] }],
      people: [{ id: "p-mum" }],
    }));
    const state = {
      items,
      people: [{ id: "p-mum", name: "Nora Hale" }],
      places: [{ id: "pl-x", name: "X" }],
      themes: [],
    };
    const main = document.createElement("main");
    placePage(main, { arg: "pl-x", query: new URLSearchParams("person=p-mum") }, state);
    const more = main.querySelector(".band-more");
    expect(more).toBeTruthy();
    expect(more.getAttribute("href")).toBe("#/timeline?place=pl-x&person=p-mum");
  });
});

describe("place page stories block", () => {
  it("renders stories about the place with the affordance", () => {
    const storyItem = {
      id: "story-1",
      title: "The Sundown gigs",
      type: "story",
      date: "1963-06",
      date_precision: "month",
      recorded: "2026-08-03",
      story: "The curator: a memory.",
      told_by: "p-alex",
      places: [{ id: "pl-x" }],
      people: [],
      themes: [],
      assets: [],
    };
    const state = {
      items: [storyItem],
      people: [{ id: "p-alex", name: "Alex Hale" }],
      places: [{ id: "pl-x", name: "X" }],
      themes: [],
    };
    const main = document.createElement("main");
    placePage(main, { arg: "pl-x", query: new URLSearchParams() }, state);
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Memories about X",
    );
    expect(block.querySelector(".response-card .response-title").textContent).toBe("The Sundown gigs");
    expect(block.querySelector("button.btn").textContent).toBe("Add a memory of X");
  });

  it("stories about a place render once — in Memories, never in the items list (2026-08-06)", () => {
    const state = {
      items: [
        {
          id: "letter-1",
          title: "A letter from Aldgate",
          type: "letter",
          date: "1963-05-14",
          date_precision: "exact",
          people: [],
          places: [{ id: "pl-aldgate" }],
          themes: [],
        },
        {
          id: "story-1",
          title: "A memory of Aldgate",
          type: "story",
          date: "1963-06",
          date_precision: "month",
          recorded: "2026-08-03",
          story: "A told memory.",
          told_by: "p-alex",
          places: [{ id: "pl-aldgate" }],
          people: [],
          themes: [],
          assets: [],
        },
      ],
      people: [{ id: "p-alex", name: "Alex Hale" }],
      places: [{ id: "pl-aldgate", name: "Aldgate" }],
      themes: [],
    };
    const main = document.createElement("main");
    placePage(main, { arg: "pl-aldgate", query: new URLSearchParams() }, state);
    const section = [...main.querySelectorAll(".section-title")].find((t) => t.textContent.startsWith("1 items from"));
    expect(section.textContent).toContain("1 items from Aldgate");
    const itemCards = [...main.querySelectorAll(".year .card-title")].map((t) => t.textContent.trim());
    expect(itemCards).toEqual(["A letter from Aldgate"]); // the story is not here
    const memories = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Memories about Aldgate",
    );
    expect(memories.textContent).toContain("A memory of Aldgate");
  });

  it("the People row lists only people attested AT the place (2026-08-05)", () => {    // The 2001 email mentions 8 places and 91 people — being mentioned in an
    // item that mentions a place is not being there. Only per-place lists
    // attest presence.
    const state = {
      items: [
        {
          id: "email-1",
          title: "The email",
          type: "document",
          date: "2001-02-07",
          date_precision: "exact",
          people: [{ id: "p-a" }, { id: "p-b" }],
          places: [{ id: "pl-x" }],
          themes: [],
        },
        {
          id: "letter-2",
          title: "The stay",
          type: "letter",
          date: "1977-01-12",
          date_precision: "exact",
          people: [{ id: "p-c" }],
          places: [{ id: "pl-x", people: ["p-c"] }],
          themes: [],
        },
      ],
      people: [
        { id: "p-a", name: "Harper Pryce" },
        { id: "p-b", name: "Lionel Tyler" },
        { id: "p-c", name: "Nora Hale" },
      ],
      places: [{ id: "pl-x", name: "X" }],
      themes: [],
    };
    const main = document.createElement("main");
    placePage(main, { arg: "pl-x", query: new URLSearchParams() }, state);
    const peopleRow = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "People",
    );
    const names = [...peopleRow.querySelectorAll(".chip")].map((c) => c.textContent.trim());
    expect(names).toEqual(["Nora Hale · 1"]);
    expect(names).not.toContain("Harper Pryce");
  });
});

describe("place involvement dates (2026-08-06)", () => {
  it("places a long-lived item by its place-ref involvement date", () => {
    const state = {
      items: [
        {
          id: "record",
          title: "The record",
          date: "1868-03-20",
          date_precision: "exact",
          type: "document",
          people: [],
          places: [{ id: "pl-bishop", date: { date: "1901-06-01", precision: "exact" } }],
          themes: [],
        },
        {
          id: "letter-1",
          title: "A 1970s letter",
          date: "1973-01-31",
          date_precision: "exact",
          type: "document",
          people: [],
          places: [{ id: "pl-bishop" }],
          themes: [],
        },
      ],
      people: [],
      places: [{ id: "pl-bishop", name: "Ravensford" }],
      themes: [],
    };
    const main = document.createElement("main");
    placePage(main, { arg: "pl-bishop", query: new URLSearchParams() }, state);
    // the record's involvement with Ravensford is 1901 (the coalfield
    // entry) — it bands with the 1900s, not the 1860s
    const nineties = [...main.querySelectorAll("details.year")].find((b) => b.querySelector(".year-number")?.textContent === "1900s");
    expect(nineties.textContent).toContain("The record");
    const seventies = [...main.querySelectorAll("details.year")].find((b) => b.querySelector(".year-number")?.textContent === "1970s");
    expect(seventies.textContent).toContain("A 1970s letter");
  });
});

describe("place evidence (2026-08-06)", () => {
  it("renders evidence records on the place they attest", () => {
    const state = {
      items: [
        {
          id: "plaque",
          title: "The Lark Inn blue plaque",
          type: "document",
          date: "2026-08-05",
          date_precision: "exact",
          evidence: true,
          people: [],
          places: [{ id: "pl-fleece" }],
          themes: [],
          assets: [],
        },
      ],
      people: [],
      places: [{ id: "pl-fleece", name: "The Lark Inn" }],
      themes: [],
    };
    const main = document.createElement("main");
    placePage(main, { arg: "pl-fleece", query: new URLSearchParams() }, state);
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Evidence",
    );
    expect(block).toBeTruthy();
    expect(block.textContent).toContain("The Lark Inn blue plaque");
  });
});
