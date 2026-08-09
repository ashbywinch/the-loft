import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "../../views/home.js";

// The moment is relative to "today" — pin the clock so the test is
// deterministic (docs/testing-standards.md: no wall-clock dependence).
// Local-time constructor, not a Z instant: the module uses local getters, so
// a UTC instant could fall on another date in extreme timezones (UTC+14).
const NOW = new Date(2026, 7, 2, 12);

const STATE = {
  items: [
    { id: "letter-1", title: "A letter", date: "1963-05-14", date_precision: "exact", type: "letter", assets: [] },
    {
      id: "letter-2",
      title: "Another letter",
      date: "1963-10-27",
      date_precision: "exact",
      type: "letter",
      assets: [],
    },
  ],
  themes: [],
};

afterEach(() => {
  vi.useRealTimers();
});

describe("home", () => {
  it('renders no anniversary moment and no "null" text when nothing is near today', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const main = document.createElement("main");
    render(main, {}, STATE);
    expect(main.querySelector(".moment")).toBeNull();
    expect(main.textContent).not.toContain("null");
  });

  it("renders the on-this-day moment when an item matches today", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const items = [
      ...STATE.items,
      { id: "letter-3", title: "This day", date: "1963-08-02", date_precision: "exact", type: "letter", assets: [] },
    ];
    const main = document.createElement("main");
    render(main, {}, { ...STATE, items });
    const moment = main.querySelector(".moment");
    expect(moment).toBeTruthy();
    expect(moment.textContent).toContain("On this day");
    expect(moment.textContent).toContain("This day");
  });

  it("never surfaces a sensitive item on serendipity surfaces (PRD §6, 2026-08-03)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const sensitive = {
      id: "doc-sensitive",
      title: "A sensitive document",
      date: "1963-08-02",
      date_precision: "exact",
      type: "document",
      assets: [],
      sensitive: true,
    };
    const items = [...STATE.items, sensitive];
    const main = document.createElement("main");
    render(main, {}, { ...STATE, items });
    // the moment excludes it even though today is its exact date
    expect(main.querySelector(".moment")).toBeNull();
    expect(main.textContent).not.toContain("A sensitive document");
    // …but the collection count stays honest: sensitive items are part of
    // the archive, just never on serendipity surfaces (2026-08-05, UX loop).
    expect(main.textContent).toContain("3 items · the full collection is still arriving");
  });

  it('counts anniversary years across New Year and pluralises "1 year"', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 0, 1, 12));
    const near = (id, title, date) => ({ id, title, date, date_precision: "exact", type: "letter", assets: [] });
    const main = document.createElement("main");
    render(main, {}, { items: [near("l-1", "Last year", "2024-12-31")], themes: [] });
    expect(main.querySelector(".moment").textContent).toContain("1 year ago this week");
    const main2 = document.createElement("main");
    render(main2, {}, { items: [near("l-2", "Old", "1963-12-31")], themes: [] });
    expect(main2.querySelector(".moment").textContent).toContain("62 years ago this week");
  });

  it('never renders "0 years ago" — an anniversary requires a past year (2026-08-05)', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    // a story told this week, dated this week: same month/day, same year
    const thisWeek = {
      id: "story-this-week",
      title: "Told this week",
      date: "2026-08-01",
      date_precision: "exact",
      type: "story",
      assets: [],
    };
    const main = document.createElement("main");
    render(main, {}, { items: [...STATE.items, thisWeek], themes: [] });
    // a same-year item is not an anniversary — no moment card at all
    expect(main.querySelector(".moment")).toBeNull();
    expect(main.textContent).not.toContain("0 years ago");
  });

  it("matches a story's actual date, never the date it was told (2026-08-05)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2027, 7, 2, 12)); // a year later — the year-check alone no longer protects
    // date == recorded: the date field IS the told-day, not an event date
    const told = {
      id: "story-told",
      title: "Told, not dated",
      date: "2026-08-01",
      date_precision: "exact",
      type: "story",
      recorded: "2026-08-01",
      assets: [],
    };
    const main = document.createElement("main");
    render(main, {}, { items: [told], themes: [] });
    expect(main.querySelector(".moment")).toBeNull();
    // a story with a real past event date, distinct from its told-day, IS a moment
    const real = {
      id: "story-real",
      title: "A memory of 1963",
      date: "1963-08-02",
      date_precision: "exact",
      type: "story",
      recorded: "2026-08-03",
      assets: [],
    };
    const main2 = document.createElement("main");
    render(main2, {}, { items: [real], themes: [] });
    const moment = main2.querySelector(".moment");
    expect(moment).toBeTruthy();
    expect(moment.textContent).toContain("On this day");
    expect(moment.textContent).toContain("A memory of 1963");
  });
});

describe("home drafts block (user, 2026-08-03: a draft is for the person who claimed it)", () => {
  const draft = (id, toldBy) => ({
    id,
    title: "The Mirosa",
    date: "2026-08-03",
    date_precision: "exact",
    type: "story",
    status: "draft",
    told_by: toldBy,
    story: "The Mirosa was moored alongside.",
    people: [],
    places: [],
    themes: [],
    items: [],
    assets: [],
    recorded: "2026-08-03",
  });
  const withPeople = (items, me = null) => ({
    items,
    themes: [],
    people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
    me,
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("lists the remembered narrator's drafts with a Continue action", () => {
    const main = document.createElement("main");
    render(main, {}, withPeople([draft("story-d1", "p-alex")], { person: "p-alex" }));
    const block = main.querySelector(".draft-card");
    expect(block).toBeTruthy();
    expect(main.textContent).toContain("Your unfinished stories");
    expect(block.querySelector("button").textContent).toContain("Continue this story");
  });

  it("hides drafts that are not the remembered narrator's", () => {
    const main = document.createElement("main");
    render(main, {}, withPeople([draft("story-d1", "p-other")], { person: "p-alex" }));
    expect(main.querySelector(".draft-card")).toBeNull();
  });

  it("shows the sign-in gate when no one is signed in", () => {
    const main = document.createElement("main");
    render(main, {}, withPeople([draft("story-d1", "p-alex")]));
    expect(main.textContent).toContain("Sign in with Google");
    expect(main.querySelector(".draft-card")).toBeNull();
  });

  it("keeps drafts out of the archive count and the recent grid", () => {
    const main = document.createElement("main");
    render(
      main,
      {},
      withPeople(
        [
          { id: "letter-1", title: "A letter", date: "1963-05-14", date_precision: "exact", type: "letter", assets: [] },
          draft("story-d1", "p-alex"),
        ],
        { person: "p-alex" },
      ),
    );
    expect(main.textContent).toContain("1 items"); // the draft is not counted
    // the draft renders only inside its own block, never in the recent grid
    expect(main.querySelector(".draft-card a").textContent).toBe("The Mirosa");
    const recentGrid = [...main.querySelectorAll("section .card-grid")].pop(); // the recent grid is the last one
    const recentTitles = [...recentGrid.querySelectorAll("a")].map((a) => a.textContent);
    expect(recentTitles.some((t) => t.includes("A letter"))).toBe(true);
    expect(recentTitles.some((t) => t.includes("The Mirosa"))).toBe(false);
  });
});

describe("home recent feed (user, 2026-08-03: recent means recently added)", () => {
  it('a story recorded today appears in "Recently in the archive" even when its events were in 1963', () => {
    const items = [
      {
        id: "letter-1",
        title: "L1",
        date: "1963-05-14",
        date_precision: "exact",
        type: "letter",
        assets: [],
        created: "1963-05-14",
      },
      {
        id: "letter-2",
        title: "L2",
        date: "1963-05-15",
        date_precision: "exact",
        type: "letter",
        assets: [],
        created: "1963-05-15",
      },
      {
        id: "letter-3",
        title: "L3",
        date: "1963-05-16",
        date_precision: "exact",
        type: "letter",
        assets: [],
        created: "1963-05-16",
      },
      {
        id: "letter-4",
        title: "L4",
        date: "1963-05-17",
        date_precision: "exact",
        type: "letter",
        assets: [],
        created: "1963-05-17",
      },
      {
        id: "letter-5",
        title: "L5",
        date: "1963-05-18",
        date_precision: "exact",
        type: "letter",
        assets: [],
        created: "1963-05-18",
      },
      // the newest thing in the archive, but its events were in May 1963
      {
        id: "story-new",
        title: "The new memory",
        date: "1963-05",
        date_precision: "month",
        type: "story",
        assets: [],
        recorded: "2026-08-03",
        created: "2026-08-03",
      },
    ];
    const main = document.createElement("main");
    render(main, {}, { items, themes: [] });
    const recentGrid = [...main.querySelectorAll("section .card-grid")].pop();
    const titles = [...recentGrid.querySelectorAll("a")].map((a) => a.textContent);
    expect(titles[0]).toContain("The new memory");
    expect(titles.some((t) => t.includes("L1"))).toBe(false); // five 1963 letters no longer crowd it out
  });
});

describe("home recent feed tie-break (user, 2026-08-03: actually recently added)", () => {
  it("created_at (full timestamp) outranks a bare recorded date", () => {
    const items = [
      {
        id: "seed-1",
        title: "Seed",
        date: "1963-05",
        date_precision: "month",
        type: "story",
        assets: [],
        recorded: "2026-08-03",
        created: "2026-08-03",
      },
      {
        id: "story-new",
        title: "The later save",
        date: "2026-08-03",
        date_precision: "exact",
        type: "story",
        assets: [],
        recorded: "2026-08-03",
        created: "2026-08-03",
        created_at: "2026-08-03T19:08:46",
      },
    ];
    const main = document.createElement("main");
    render(main, {}, { items, themes: [] });
    const recentGrid = [...main.querySelectorAll("section .card-grid")].pop();
    const titles = [...recentGrid.querySelectorAll("a")].map((a) => a.textContent);
    expect(titles[0]).toContain("The later save");
  });
});

describe("home drafts gate (user, 2026-08-03: incognito must still find the drafts)", () => {
  const draft = (id, toldBy) => ({
    id,
    title: "The Mirosa",
    date: "2026-08-03",
    date_precision: "exact",
    type: "story",
    status: "draft",
    told_by: toldBy,
    story: "The Mirosa was moored alongside.",
    people: [],
    places: [],
    themes: [],
    items: [],
    assets: [],
    recorded: "2026-08-03",
  });
  const withPeople = (items, me = null) => ({
    items,
    themes: [],
    people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
    me,
  });

  it("a signed-out window is asked to sign in before the drafts show", () => {
    const main = document.createElement("main");
    render(main, {}, withPeople([draft("story-d1", "p-alex")]));
    expect(main.textContent).toContain("Unfinished stories");
    expect(main.querySelector(".draft-card")).toBeNull(); // not shown until signed in
    const gate = main.querySelector(".drafts-gate");
    expect(gate.textContent).toContain("Sign in with Google");
    expect(gate.querySelector("button")).toBeTruthy(); // the device-flow sheet, not a redirect
  });

  it("the signed-in person sees their drafts", () => {
    const main = document.createElement("main");
    render(main, {}, withPeople([draft("story-d1", "p-alex")], { person: "p-alex" }));
    const card = main.querySelector(".draft-card");
    expect(card).toBeTruthy();
    expect(card.querySelector("button").textContent).toContain("Continue this story");
  });

  it("no drafts anywhere means no gate and no block", () => {
    const main = document.createElement("main");
    render(main, {}, { items: [], themes: [], people: [] });
    expect(main.textContent).not.toContain("Unfinished");
    expect(main.querySelector(".drafts-gate")).toBeNull();
  });

  it("never asks for a name — the identity is the session", () => {
    const main = document.createElement("main");
    render(main, {}, withPeople([draft("story-d1", "p-alex")]));
    expect(main.querySelector(".drafts-gate .ac")).toBeNull(); // no name picker, ever
    expect(main.textContent).toContain("Sign in with Google");
  });
});

describe("home orientation (2026-08-06, Eli walk)", () => {
  it("names the tree door and keeps the people subtitle honest", () => {
    const main = document.createElement("main");
    render(main, {}, STATE);
    const door = [...main.querySelectorAll(".door")].find((d) => d.textContent.includes("Family Tree"));
    expect(door).toBeTruthy();
    expect(door.textContent).toContain("who's who, and how they're related");
    expect(main.querySelectorAll(".door").length).toBe(6);
  });

  it("explains how things get into the archive", () => {
    const main = document.createElement("main");
    render(main, {}, STATE);
    expect(main.textContent).toContain("Letters and documents are added by the family");
    expect(main.textContent).toContain("anyone can add a memory");
  });
});



describe("the home sign-in affordance (2026-08-06)", () => {
  it("shows a Sign in button in the top bar when signed out — even with no drafts", () => {
    const main = document.createElement("main");
    render(main, {}, { ...STATE, items: [], themes: [], me: null });
    const identity = main.querySelector(".topbar .topbar-identity");
    expect(identity).toBeTruthy();
    expect(identity.textContent).toContain("Sign in");
  });

  it("signed in shows the avatar; the account sheet carries the name and Sign out", () => {
    const main = document.createElement("main");
    render(main, {}, { ...STATE, themes: [], people: [{ id: "p-alex", name: "Alex Hale" }], me: { name: "Alex Hale", person: "p-alex", email: "alex.hale@example.com" } });
    const identity = main.querySelector(".topbar .topbar-identity");
    const avatar = identity.querySelector("img.topbar-avatar");
    expect(avatar).toBeTruthy();
    expect(avatar.getAttribute("src")).toContain("avatar-p-alex.svg");
    avatar.click(); // the account sheet opens: name, email, Sign out
    const sheet = document.querySelector(".account-sheet");
    expect(sheet).toBeTruthy();
    expect(sheet.textContent).toContain("Alex Hale");
    expect(sheet.textContent).toContain("alex.hale@example.com");
    expect(sheet.textContent).toContain("Sign out");
  });
});

describe("the unfinished import session (2026-08-07, user: the front page shows the session, never the pending people)", () => {
  const pendingState = (imports, people, me) => ({
    ...STATE,
    imports,
    people,
    ...(me ? { me } : {}),
  });

  it("the signed-in owner sees the session card with the count and a review link", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const main = document.createElement("main");
    render(
      main,
      {},
      pendingState(
        [{ id: "import-documents", title: "The document import", status: "pending" }],
        [{ id: "p-judith", name: "Pearl Whitlock", relation: "cousin", status: "proposed" }],
        { person: "p-alex" },
      ),
    );
    expect(main.textContent).toContain("The document import");
    expect(main.textContent).toContain("1 person");
    expect(main.querySelector('a[href="#/import/import-documents"]')).not.toBeNull();
    expect(main.textContent).not.toContain("Pearl Whitlock"); // the raw list never renders on the front page
  });

  it("visitors never see the import session", () => {
    const main = document.createElement("main");
    render(main, {}, pendingState([{ id: "import-documents", title: "The document import", status: "pending" }], [], null));
    expect(main.textContent).not.toContain("The document import");
  });

  it("no session card when the import is finished or nothing is pending", () => {
    const main = document.createElement("main");
    render(main, {}, pendingState([{ id: "import-documents", title: "The document import", status: "reviewed" }], [], { person: "p-alex" }));
    expect(main.textContent).not.toContain("The document import");
    render(main, {}, pendingState([], [], { person: "p-alex" }));
    expect(main.textContent).not.toContain("The document import");
  });
});
