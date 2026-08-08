import { describe, expect, it } from "vitest";
import { aggregate, clarificationsFor, decadeBands, itemDateFor, itemInvolves, personAtPlace, referencedBy, sortedCounts, windowFromQuery } from "../connections.js";

const ITEMS = [
  { id: "a", date: "1963-05-14", people: [{ id: "p-mum" }], places: [{ id: "pl-aldgate" }], themes: [{ id: "t-x" }] },
  {
    id: "b",
    date: "1964-08-09",
    people: [{ id: "p-mum" }, { id: "p-dad" }],
    places: [{ id: "pl-sundown" }],
    themes: [{ id: "t-x" }],
  },
  {
    id: "c",
    date: "1980-01-01",
    people: [{ id: "p-dad" }],
    places: [{ id: "pl-farndale-wharf" }],
    themes: [{ id: "t-boats" }],
  },
];

describe("personAtPlace — the one attribution rule (2026-08-03 review)", () => {
  const item = {
    id: "letter",
    people: [{ id: "p-writer" }, { id: "p-recipient" }],
    places: [{ id: "pl-home", people: ["p-writer"] }, { id: "pl-plain" }],
  };

  it("an explicit per-place people list is authoritative — even for someone outside the item people", () => {
    expect(personAtPlace("p-writer", item.places[0])).toBe(true);
    expect(personAtPlace("p-recipient", item.places[0])).toBe(false);
    expect(personAtPlace("p-outsider", item.places[0])).toBe(false);
  });

  it("without a per-place list, co-mention is not presence (2026-08-05)", () => {
    // An item mentioning a place links nobody to it — the 2001 email's 91
    // people and 8 places are mentions, not attestations that anyone was
    // anywhere. Presence must be attested per place.
    expect(personAtPlace("p-writer", item.places[1])).toBe(false);
    expect(personAtPlace("p-recipient", item.places[1])).toBe(false);
  });

  it("a multi-person item mentioning a place links none of them there", () => {
    const email = {
      id: "email",
      people: [{ id: "p-1" }, { id: "p-2" }, { id: "p-3" }],
      places: [{ id: "pl-kirkby" }, { id: "pl-grimsford" }, { id: "pl-hollowdene" }],
    };
    for (const person of email.people) {
      for (const place of email.places) {
        expect(personAtPlace(person.id, place)).toBe(false);
      }
    }
  });
});

describe("itemInvolves — a person is a subject or a teller", () => {
  it("includes told_by even when the person is not in people[]", () => {
    const item = { id: "s", people: [{ id: "p-dad" }], told_by: "p-alex" };
    expect(itemInvolves(item, "p-alex")).toBe(true);
    expect(itemInvolves(item, "p-dad")).toBe(true);
    expect(itemInvolves(item, "p-mum")).toBe(false);
  });
});

describe("aggregate — everything-to-everything counts", () => {
  it("counts each entity across items", () => {
    const agg = aggregate(ITEMS);
    expect(agg.people.get("p-mum")).toBe(2);
    expect(agg.people.get("p-dad")).toBe(2);
    expect(agg.places.get("pl-aldgate")).toBe(1);
    expect(agg.places.get("pl-sundown")).toBe(1);
    expect(agg.themes.get("t-x")).toBe(2);
  });

  it("tolerates items without links", () => {
    const agg = aggregate([{ id: "x", date: "1970" }]);
    expect(agg.people.size).toBe(0);
  });

  it("with a person: a place attaches only to the people AT it (2026-08-03)", () => {
    // the 1977-letter shape: the writer's gigs, the in-laws' house, and the
    // sister-in-law's Tornia are nobody else's places — least of all the recipient's
    const letter = {
      id: "letter-1977",
      people: [
        { id: "p-writer" },
        { id: "p-recipient" },
        { id: "p-husband" },
        { id: "p-inlaws" },
        { id: "p-sister-in-law" },
      ],
      places: [
        { id: "pl-home", people: ["p-writer", "p-husband"] },
        { id: "pl-gig", people: ["p-writer"] },
        { id: "pl-inlaw-house", people: ["p-inlaws"] },
        { id: "pl-tornia", people: ["p-sister-in-law"] },
      ],
    };
    const agg = aggregate([letter], "p-recipient");
    expect(agg.places.size).toBe(0); // the recipient is not at any of them
    expect(aggregate([letter], "p-writer").places.get("pl-gig")).toBe(1);
    expect(aggregate([letter], "p-husband").places.get("pl-home")).toBe(1);
    expect(aggregate([letter], "p-husband").places.has("pl-gig")).toBe(false);
    expect(aggregate([letter], "p-sister-in-law").places.get("pl-tornia")).toBe(1);
  });

  it("with a person: a place without an explicit people list attaches to nobody (2026-08-05)", () => {
    // "we sailed" is not an attestation that everyone was at the iron wharf —
    // presence is per-place or it is nothing.
    const item = {
      id: "boat",
      people: [{ id: "p-dad" }, { id: "p-kid" }], // "we" sailed
      places: [{ id: "pl-farndale-wharf" }],
    };
    expect(aggregate([item], "p-dad").places.size).toBe(0);
    expect(aggregate([item], "p-kid").places.size).toBe(0);
    expect(aggregate([item], "p-stranger").places.size).toBe(0);
    const attested = { ...item, places: [{ id: "pl-farndale-wharf", people: ["p-dad"] }] };
    expect(aggregate([attested], "p-dad").places.get("pl-farndale-wharf")).toBe(1);
    expect(aggregate([attested], "p-kid").places.size).toBe(0);
  });

  it("with a person: a story the person merely told never gives them its places", () => {
    const story = { id: "s", told_by: "p-alex", people: [{ id: "p-dad" }], places: [{ id: "pl-yard", people: ["p-dad"] }] };
    expect(aggregate([story], "p-alex").places.size).toBe(0);
    expect(aggregate([story], "p-dad").places.get("pl-yard")).toBe(1);
  });
});

describe("sortedCounts", () => {
  it("sorts by count desc and caps", () => {
    const map = new Map([
      ["a", 1],
      ["b", 5],
      ["c", 3],
    ]);
    expect(sortedCounts(map, 2).map(([id]) => id)).toEqual(["b", "c"]);
  });
});

describe("decadeBands", () => {
  it("groups by decade, most recent first", () => {
    const bands = decadeBands(ITEMS);
    expect(bands.map((b) => b.decade)).toEqual([1980, 1960]);
    expect(bands[1].items.length).toBe(2);
  });

  it("skips malformed dates instead of grouping them under a NaN decade", () => {
    const bands = decadeBands([{ id: "x", date: "not-a-date" }, ...ITEMS]);
    expect(bands.some((b) => Number.isNaN(b.decade))).toBe(false);
    expect(bands.map((b) => b.decade)).toEqual([1980, 1960]);
  });
});

describe("windowFromQuery", () => {
  it("absent params mean no window", () => {
    expect(windowFromQuery(new URLSearchParams("")).inWindow).toBe(false);
  });
  it("valid params mean a window", () => {
    const w = windowFromQuery(new URLSearchParams("from=1961&to=1965"));
    expect(w).toEqual({ inWindow: true, from: 1961, to: 1965 });
  });
  it("invalid params are treated as no window (Number(null) is 0 — the bug)", () => {
    expect(windowFromQuery(new URLSearchParams("from=abc&to=def")).inWindow).toBe(false);
  });
  it('empty params are treated as no window (Number("") is 0 — the bug)', () => {
    expect(windowFromQuery(new URLSearchParams("from=&to=")).inWindow).toBe(false);
    expect(windowFromQuery(new URLSearchParams("from=  &to=  ")).inWindow).toBe(false);
  });
});

describe("clarificationsFor — the fragments that attest a target (2026-08-06)", () => {
  it("returns clarification stories that name the target in people or items refs", () => {
    const items = [
      { id: "c1", clarification: true, people: [{ id: "p-owen" }], items: [] },
      { id: "c2", clarification: true, people: [], items: [{ id: "letter-1977" }] },
      { id: "c3", clarification: true, people: [{ id: "p-someone-else" }], items: [] },
      { id: "s", people: [{ id: "p-owen" }] }, // a plain story is not a clarification
    ];
    expect(clarificationsFor(items, "p-owen").map((i) => i.id)).toEqual(["c1"]);
    expect(clarificationsFor(items, "letter-1977").map((i) => i.id)).toEqual(["c2"]);
    expect(clarificationsFor(items, "p-someone-else").map((i) => i.id)).toEqual(["c3"]);
  });
});

describe("itemDateFor — placement by involvement (2026-08-06)", () => {
  const record = { id: "r", date: "1868-03-20", people: [{ id: "p-isabella" }, { id: "p-nora", date: { date: "1947-05-11", precision: "exact" } }] };

  it("derives the involvement from the invariant: not before the item, not before the person", () => {
    expect(itemDateFor(record, { id: "p-isabella", dob: { date: "1844-06-01", precision: "exact" } })).toBe("1868-03-20");
    expect(itemDateFor(record, { id: "p-nora", dob: { date: "1947-05-11", precision: "exact" } })).toBe("1947-05-11");
    // the item's own date for someone with no dob
    expect(itemDateFor(record, { id: "p-stranger" })).toBe("1868-03-20");
  });

  it("an attested ref date overrides the derivation (a death-only entry)", () => {
    const rec = { id: "r", date: "1868-03-20", people: [{ id: "p-x", date: { date: "1950-02-01", precision: "exact" } }] };
    expect(itemDateFor(rec, { id: "p-x", dob: { date: "1880-01-01", precision: "exact" } })).toBe("1950-02-01");
  });
});

describe("referencedBy — the back link (2026-08-06)", () => {
  it("finds every item that references the target in its items refs", () => {
    const items = [
      { id: "story-1", items: [{ id: "object-sunlight" }] },
      { id: "story-2", items: [{ id: "object-sunlight" }, { id: "object-yard" }] },
      { id: "letter-1", items: [] },
    ];
    expect(referencedBy(items, "object-sunlight").map((i) => i.id)).toEqual(["story-1", "story-2"]);
    expect(referencedBy(items, "letter-1")).toEqual([]);
  });
});
