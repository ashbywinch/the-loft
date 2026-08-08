import { describe, expect, it } from "vitest";
import { bucketPeriods, lifeEvents, periodHook, periodRange, render } from "../../views/timeline.js";

const entry = (date, overrides = {}) => ({ date, ...overrides });

describe("timeline", () => {
  it("skips items with a malformed date instead of grouping them under a NaN year", () => {
    const main = document.createElement("main");
    render(
      main,
      { arg: null, query: new URLSearchParams() },
      {
        items: [{ id: "bad", title: "Broken date", date: "not-a-date", date_precision: "exact", type: "letter" }],
        people: [],
        places: [],
      },
    );
    expect(main.textContent).not.toContain("NaN");
  });

  it("offers a Stories filter and filters by type (2026-08-03)", () => {
    const state = {
      items: [
        { id: "l", title: "A letter", date: "1963-05-14", date_precision: "exact", type: "letter" },
        { id: "s", title: "A comment", date: "2026-08-02", date_precision: "exact", type: "story" },
      ],
      people: [],
      places: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams("type=story") }, state);
    expect(main.textContent).toContain("A comment");
    expect(main.textContent).not.toContain("A letter");
    expect(main.querySelectorAll(".chip").length).toBeGreaterThanOrEqual(5); // incl. Stories
  });
});

describe("timeline periods (2026-08-05)", () => {
  it("packs the chronological spine into count-sized, year-aligned buckets", () => {
    const entries = [];
    for (let i = 0; i < 25; i++) entries.push(entry(`${1960 + i}-05-01`)); // 1960–1984, one per year
    for (let i = 0; i < 5; i++) entries.push(entry(`1990-01-${String(i + 1).padStart(2, "0")}`));
    const periods = bucketPeriods(entries, 20);
    expect(periods.length).toBe(2);
    expect(periods[0].length).toBe(20);
    expect(periods[1].length).toBe(10);
    // the 1960s–70s entries stay together — a year is never split across buckets
    expect(periods[0].every((e) => Number(e.date.slice(0, 4)) <= 1979)).toBe(true);
    expect(periods[1].every((e) => Number(e.date.slice(0, 4)) >= 1980)).toBe(true);
  });

  it("a single year larger than the target is its own period", () => {
    const entries = [];
    for (let i = 0; i < 45; i++) entries.push(entry(`2026-08-03`));
    const periods = bucketPeriods(entries, 20);
    expect(periods.length).toBe(3);
    expect(periods.map((p) => p.length)).toEqual([20, 20, 5]);
  });

  it("reports the period's date range — a single year is just that year", () => {
    expect(periodRange([entry("1830-05-03"), entry("1830-09-02")])).toBe("1830");
    expect(periodRange([entry("1868-03-20"), entry("1949-01-27")])).toBe("1868–1949");
  });

  it("names a period after its dominant theme — the hook (2026-08-05)", () => {
    const items = [
      entry("1949-01-27", { themes: [{ id: "t-boats" }] }),
      entry("1949-02-04", { themes: [{ id: "t-boats" }] }),
      entry("1950-06-01", { themes: [{ id: "t-boats" }] }),
      entry("1951-06-01", { themes: [{ id: "t-music" }] }),
      entry("1952-06-01", { themes: [{ id: "t-music" }] }),
    ];
    expect(periodHook(items)).toBe("t-boats");
    // a theme on a single item is not the period's key content
    expect(periodHook([entry("1949-01-27", { themes: [{ id: "t-boats" }] }), entry("1949-02-04")])).toBeNull();
    // life events carry no themes — they never dilute the items' share
    const diluted = [
      entry("1949-01-27", { themes: [{ id: "t-boats" }] }),
      entry("1949-02-04", { themes: [{ id: "t-boats" }] }),
      entry("1950-01-01", { derived: true }),
      entry("1950-02-01", { derived: true }),
      entry("1950-03-01", { derived: true }),
    ];
    expect(periodHook(diluted)).toBe("t-boats"); // 2 of 2 items, despite 3 events
  });
});

describe("life events on the timeline (2026-08-05)", () => {
  it("derives birth and death events from a person's dated facts", () => {
    const people = [
      { id: "p-harper", name: "Harper Pryce", dob: { date: "1830-05-03", precision: "exact" }, dod: { date: "1911-06-22", precision: "exact" } },
    ];
    const events = lifeEvents(people, []);
    expect(events).toEqual([
      { date: "1830-05-03", precision: "exact", kind: "birth", people: [{ id: "p-harper", name: "Harper Pryce" }], derived: true },
      { date: "1911-06-22", precision: "exact", kind: "death", people: [{ id: "p-harper", name: "Harper Pryce" }], derived: true },
    ]);
  });

  it("derives a marriage event from a dated spouse edge", () => {
    const people = [
      { id: "p-a", name: "A" },
      { id: "p-b", name: "B" },
    ];
    const events = lifeEvents(people, [
      { a: "p-a", b: "p-b", kind: "spouse", label_a: "spouse", label_b: "spouse", date: { date: "1888-06-20", precision: "exact" } },
    ]);
    expect(events).toEqual([
      { date: "1888-06-20", precision: "exact", kind: "marriage", people: [{ id: "p-a", name: "A" }, { id: "p-b", name: "B" }], derived: true },
    ]);
  });

  it("carries the calculated ages at marriage on the card (2026-08-06)", () => {
    const people = [
      { id: "p-a", name: "Harper Pryce", dob: { date: "1830-05-03", precision: "exact" } },
      { id: "p-b", name: "Lionel Tyler", dob: { date: "1834-01-10", precision: "exact" } },
    ];
    const state = {
      items: [],
      people,
      places: [],
      relationships: [
        { a: "p-a", b: "p-b", kind: "spouse", label_a: "spouse", label_b: "spouse", date: { date: "1888-06-20", precision: "exact" } },
      ],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    const card = main.querySelector(".event-card");
    expect(card.textContent).toContain("Harper Pryce and Lionel Tyler · married 20 Jun 1888");
    expect(card.textContent).toContain("(aged 58 · 54)");
  });

  it("ignores undated people and undated relationships", () => {
    const people = [{ id: "p-x", name: "X" }];
    const events = lifeEvents(people, [
      { a: "p-x", b: "p-nobody", kind: "spouse", label_a: "spouse", label_b: "spouse" },
    ]);
    expect(events).toEqual([]);
  });

  it("renders a birth in its period as a card linking to the person", () => {
    const state = {
      items: [{ id: "l", title: "A letter", date: "1963-05-14", date_precision: "exact", type: "letter" }],
      people: [{ id: "p-harper", name: "Harper Pryce", dob: { date: "1830-05-03", precision: "exact" } }],
      places: [],
      relationships: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    expect(main.textContent).toContain("Harper Pryce · born");
    const card = [...main.querySelectorAll(".event-card")].find((c) => c.textContent.includes("Harper Pryce"));
    expect(card.getAttribute("href")).toBe("#/person/p-harper");
    // the card carries its own date — a period's range must never be
    // misread as the event's date (2026-08-06: "died" inside "1972–1981"
    // read as "died after 1972")
    expect(card.textContent).toContain("3 May 1830");
    const period = [...main.querySelectorAll("details.period")].find((d) =>
      d.querySelector(".period-range")?.textContent === "1830–1963",
    );
    expect(period).toBeTruthy();
    expect(period.textContent).toContain("2 entries");
  });

  it("counts periods, items and events honestly in the header", () => {
    const state = {
      items: [{ id: "l", title: "A letter", date: "1963-05-14", date_precision: "exact", type: "letter" }],
      people: [{ id: "p-harper", name: "Harper Pryce", dob: { date: "1830-05-03", precision: "exact" } }],
      places: [],
      relationships: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    expect(main.textContent).toContain("1 period, 1 item · 1 event");
  });

  it("a person filter includes their life events", () => {
    const state = {
      items: [{ id: "l", title: "A letter", date: "1828-06-01", date_precision: "exact", type: "letter" }],
      people: [{ id: "p-harper", name: "Harper Pryce", dob: { date: "1830-05-03", precision: "exact" } }],
      places: [],
      relationships: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams("person=p-harper") }, state);
    expect(main.textContent).toContain("Harper Pryce · born");
  });

  it("the Events filter shows derived life events and stored event items", () => {
    const state = {
      items: [
        { id: "l", title: "A letter", date: "1828-06-01", date_precision: "exact", type: "letter" },
        { id: "ev", title: "The concert", date: "1949-06-01", date_precision: "exact", type: "event", kind: "other" },
      ],
      people: [{ id: "p-harper", name: "Harper Pryce", dob: { date: "1830-05-03", precision: "exact" } }],
      places: [],
      relationships: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams("type=event") }, state);
    expect(main.textContent).toContain("Harper Pryce · born");
    expect(main.textContent).toContain("The concert");
    expect(main.textContent).not.toContain("A letter");
  });

  it("the deep link to a year opens the period containing it", () => {
    const state = {
      items: [
        { id: "a", title: "A", date: "1868-03-20", date_precision: "exact", type: "document" },
        { id: "b", title: "B", date: "1949-01-27", date_precision: "exact", type: "letter" },
      ],
      people: [],
      places: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: "1949", query: new URLSearchParams() }, state);
    const open = [...main.querySelectorAll("details.period[open]")];
    expect(open.length).toBe(1);
    expect(open[0].textContent).toContain("B");
  });

  it("renders periods most recent first", () => {
    const items = [{ id: "new", title: "New", date: "2001-02-07", date_precision: "exact", type: "document" }];
    for (let i = 0; i < 24; i++) {
      items.push({ id: `old-${i}`, title: `Old ${i}`, date: `${1860 + i}-03-20`, date_precision: "exact", type: "document" });
    }
    const state = { items, people: [], places: [], themes: [] };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    const ranges = [...main.querySelectorAll(".period-range")].map((r) => r.textContent);
    expect(ranges[0]).toBe("1880–2001");
    expect(ranges[ranges.length - 1]).toBe("1860–1879");
  });

  it("sorts entries newest first within a period (2026-08-06)", () => {
    const state = {
      items: [
        { id: "a", title: "Oldest", date: "1949-01-27", date_precision: "exact", type: "letter" },
        { id: "b", title: "Middle", date: "1963-05-14", date_precision: "exact", type: "letter" },
        { id: "c", title: "Newest", date: "1977-01-12", date_precision: "exact", type: "letter" },
      ],
      people: [],
      places: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    const titles = [...main.querySelectorAll("details.period .card-title")].map((t) => t.textContent);
    expect(titles).toEqual(["Newest", "Middle", "Oldest"]);
  });

  it("clarification fragments never render on the timeline (2026-08-06)", () => {
    // "yes BF means Owen" is not an event — it appears only on the page of
    // what it attests.
    const state = {
      items: [
        { id: "l", title: "A letter", date: "1963-05-14", date_precision: "exact", type: "letter" },
        {
          id: "c",
          title: "BF",
          date: "2026-08-02",
          date_precision: "exact",
          type: "story",
          clarification: true,
          people: [{ id: "p-owen" }],
        },
      ],
      people: [],
      places: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    expect(main.textContent).not.toContain("BF");
    expect(main.textContent).toContain("A letter");
  });

  it("evidence records — found material, not family happenings — never render (2026-08-06)", () => {
    // The blue-plaque capture is genuinely dated 2026, but nothing happened
    // to the family in 2026 (or ever): it attests the place, it is not a
    // happening. It lives on the pages it attests.
    const state = {
      items: [
        { id: "l", title: "A letter", date: "1963-05-14", date_precision: "exact", type: "letter" },
        {
          id: "plaque",
          title: "The Lark Inn blue plaque",
          date: "2026-08-05",
          date_precision: "exact",
          type: "document",
          evidence: true,
          places: [{ id: "pl-fleece" }],
        },
      ],
      people: [],
      places: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    expect(main.textContent).not.toContain("blue plaque");
    expect(main.textContent).toContain("A letter");
  });

  it("a non-point death (after/before/between) never renders as a year point (2026-08-06)", () => {
    // "died after 1917" is not a 1917 happening — the fact stays on the
    // person page, but the timeline must not place it at the bound year.
    const events = lifeEvents(
      [{ id: "p-r", name: "Walter", dod: { date: "1917", precision: "after" } }],
      [],
    );
    expect(events).toEqual([]);
  });

  it("a period with a dominant theme shows the hook in its summary", () => {
    const state = {
      items: [
        { id: "a", title: "A", date: "1949-01-27", date_precision: "exact", type: "letter", themes: [{ id: "t-boats" }] },
        { id: "b", title: "B", date: "1949-02-04", date_precision: "exact", type: "letter", themes: [{ id: "t-boats" }] },
        { id: "c", title: "C", date: "1963-05-14", date_precision: "exact", type: "letter", themes: [{ id: "t-boats" }] },
        { id: "d", title: "D", date: "1963-06-01", date_precision: "exact", type: "letter", themes: [{ id: "t-music" }] },
      ],
      people: [],
      places: [],
      themes: [{ id: "t-boats", title: "The boats" }, { id: "t-music", title: "The music years" }],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    const period = main.querySelector("details.period .period-hook");
    expect(period.textContent).toContain("The boats");
  });
});

describe("person-filtered placement (2026-08-06)", () => {
  it("places the family record at the person's involvement year, not its own", () => {
    const state = {
      items: [
        {
          id: "record",
          title: "Kendall–Pryce family record",
          date: "1868-03-20",
          date_precision: "exact",
          type: "document",
          people: [{ id: "p-nora", date: { date: "1947-05-11", precision: "exact" } }],
          places: [],
          themes: [],
        },
      ],
      people: [{ id: "p-nora", name: "Nora Hale" }],
      places: [],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams("person=p-nora") }, state);
    const recordPeriod = [...main.querySelectorAll("details.period")].find((p) =>
      p.textContent.includes("Kendall–Pryce family record"),
    );
    expect(recordPeriod.querySelector(".period-range").textContent).toBe("1947");
    expect(recordPeriod.textContent).not.toContain("1868");
  });
});

describe("proposed facts (2026-08-06)", () => {
  it("a proposed person's dated facts never render as events", () => {
    const events = lifeEvents(
      [{ id: "p-x", name: "X", status: "proposed", dob: { date: "1910", precision: "year" } }],
      [],
    );
    expect(events).toEqual([]);
  });
});

describe("same-name disambiguation on life events (2026-08-06)", () => {
  it("carries a distinguishing detail on birth/death events", () => {
    const people = [
      { id: "p-sr", name: "Walter Kendall", dob: { date: "1830-09-02", precision: "exact" } },
      { id: "p-jr", name: "Walter Kendall", dob: { date: "1895-08-27", precision: "exact" }, occupations: ["vicar"] },
      { id: "p-eleanor", name: "Clara Kendall" },
      { id: "p-alice", name: "Beatrice Beth Kendall" },
    ];
    const rels = [
      { a: "p-sr", b: "p-eleanor", kind: "spouse" },
      { a: "p-jr", b: "p-alice", kind: "spouse" },
    ];
    const events = lifeEvents(people, rels);
    const details = events.filter((e) => e.kind === "birth").map((e) => e.people[0].detail);
    expect(details).toEqual(["married Clara Kendall", "married Beatrice Beth Kendall"]);
  });

  it("skips an unknown-named spouse when a named one exists", () => {
    const people = [
      { id: "p-harper", name: "Harper Pryce", dob: { date: "1830-05-03", precision: "exact" } },
      { id: "p-q", name: "? Corbett" },
      { id: "p-tate", name: "Lionel Tyler" },
    ];
    const events = lifeEvents(people, [
      { a: "p-harper", b: "p-q", kind: "spouse" },
      { a: "p-harper", b: "p-tate", kind: "spouse" },
    ]);
    expect(events.find((e) => e.kind === "birth").people[0].detail).toBe("married Lionel Tyler");
  });

  it("renders the detail on the event card — the two Walter Kendalls differ", () => {
    const people = [
      { id: "p-sr", name: "Walter Kendall", dob: { date: "1830-09-02", precision: "exact" } },
      { id: "p-jr", name: "Walter Kendall", dob: { date: "1895-08-27", precision: "exact" }, occupations: ["vicar"] },
      { id: "p-eleanor", name: "Clara Kendall" },
      { id: "p-alice", name: "Beatrice Beth Kendall" },
    ];
    const state = {
      items: [],
      people,
      places: [],
      relationships: [
        { a: "p-sr", b: "p-eleanor", kind: "spouse" },
        { a: "p-jr", b: "p-alice", kind: "spouse" },
      ],
      themes: [],
    };
    const main = document.createElement("main");
    render(main, { arg: null, query: new URLSearchParams() }, state);
    const cards = [...main.querySelectorAll(".event-card")];
    const births = cards.filter((c) => c.textContent.includes("born"));
    expect(births.some((c) => c.textContent.includes("born 2 Sep 1830 · married Clara Kendall"))).toBe(true);
    expect(births.some((c) => c.textContent.includes("born 27 Aug 1895 · married Beatrice Beth Kendall"))).toBe(true);
  });
});

describe("photos empty state (2026-08-06, Eli walk)", () => {
  it("says photos are supported but not yet added — never that they don't exist", () => {
    const main = document.createElement("main");
    render(
      main,
      { arg: null, query: new URLSearchParams("type=photo") },
      { items: [], people: [], places: [], themes: [] },
    );
    expect(main.textContent).toContain("No photos yet — the collection is still growing");
  });
});
