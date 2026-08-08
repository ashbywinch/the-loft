import { describe, expect, it } from "vitest";
import { personPage, render } from "../../views/cast.js";

const STATE = {
  people: [{ id: "p-mum", name: "Nora Hale", aliases: [], relation: "", bio: "" }],
  places: [{ id: "pl-aldgate", name: "Aldgate" }],
  themes: [{ id: "t-music", title: "The music years" }],
  items: [
    {
      id: "letter-1",
      title: "A letter",
      date: "1963-05-14",
      date_precision: "exact",
      type: "letter",
      people: [{ id: "p-mum" }],
      places: [{ id: "pl-aldgate", people: ["p-mum"] }],
      themes: [{ id: "t-music" }],
      assets: [],
    },
  ],
  byId: new Map(),
};

describe("person page connections", () => {
  it("renders place and theme chips with names, not ids", () => {
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, STATE);
    const chips = [...main.querySelectorAll(".block .chips .chip")].map((c) => c.textContent.trim());
    expect(chips).toContain("Aldgate · 1");
    expect(chips).toContain("The music years · 1");
    expect(chips.some((c) => c.includes("pl-"))).toBe(false);
  });

  it('omits empty connection rows instead of appending literal "null" text', () => {
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, { ...STATE, items: [], byId: new Map() });
    expect(main.textContent).not.toContain("null");
    // the memories block renders even with nothing to list — connection rows stay absent
    expect(main.querySelectorAll(".block .chips").length).toBe(0);
  });

  it("shows clarification fragments only in a Clarifications block, never as artifacts (2026-08-06)", () => {
    const clar = {
      id: "c-bf",
      title: "BF",
      date: "2026-08-02",
      date_precision: "exact",
      type: "story",
      clarification: true,
      told_by: "p-alex",
      recorded: "2026-08-03",
      story: "Owen is BF (Best Friend), yes.",
      people: [{ id: "p-mum" }],
      places: [],
      themes: [],
      assets: [],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, { ...STATE, items: [clar], byId: new Map() });
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Clarifications",
    );
    expect(block).toBeTruthy();
    expect(block.textContent).toContain("Owen is BF");
    // never as an artifact card in the involved lists
    expect(main.querySelector(".card-title")).toBeNull();
  });

  it("shows the dates and facts we know, with honest precision (2026-08-06)", () => {
    const st = {
      ...STATE,
      people: [
        {
          id: "p-mum",
          name: "Nora Hale",
          aliases: ["Alex"],
          relation: "",
          bio: "",
          pronouns: "she/her",
          dob: { date: "1947-05-11", precision: "exact" },
          dod: { date: "2010", precision: "after" },
          occupations: ["solicitor's clerk"],
          residence: [{ place: "pl-town", from: "1963", to: "1977", status: "confirmed" }],
        },
      ],
      places: [{ id: "pl-town", name: "Stonewick" }],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, st);
    const text = main.querySelector(".person").textContent;
    expect(text).toContain("b. 11 May 1947");
    expect(text).toContain("d. after 2010"); // never "2010" — a bound is not a point
    expect(text).toContain("Occupation: solicitor's clerk");
    expect(text).toContain("Stonewick, 1963–1977");
    expect(text).toContain("Pronouns: she/her");
    expect(text).toContain("Known as: Alex");
  });

  it("shows the calculated age at death — never stored (2026-08-06)", () => {
    const st = {
      ...STATE,
      people: [
        {
          id: "p-mum",
          name: "Nora Hale",
          aliases: [],
          relation: "",
          bio: "",
          dob: { date: "1896-02-29", precision: "exact" },
          dod: { date: "1982-05-16", precision: "exact" },
        },
      ],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, st);
    const text = main.querySelector(".person").textContent;
    expect(text).toContain("d. 16 May 1982 (aged 86)");
  });

  it("shows the marriage date and the subject's age at it on the spouse chip (2026-08-06)", () => {
    const st = {
      ...STATE,
      relationships: [
        { a: "p-mum", b: "p-dad", kind: "spouse", label_a: "husband", label_b: "wife", date: { date: "1966-06-20", precision: "exact" } },
      ],
      people: [
        { id: "p-mum", name: "Nora Hale", aliases: [], relation: "", bio: "", dob: { date: "1947-05-11", precision: "exact" } },
        { id: "p-dad", name: "Owen Hale", aliases: [], relation: "", bio: "" },
      ],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, st);
    const peopleBlock = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "People",
    );
    const people = [...peopleBlock.querySelectorAll(".chip")].map((c) => c.textContent.trim());
    expect(people).toEqual(["Owen Hale — husband (m. 20 Jun 1966, aged 19)"]);
  });

  it("labels attested relationships; co-mention alone never links (2026-08-06)", () => {    const st = {
      ...STATE,
      relationships: [{ a: "p-mum", b: "p-dad", kind: "spouse", label_a: "husband", label_b: "wife" }],
      people: [
        { id: "p-mum", name: "Nora Hale", aliases: [], relation: "", bio: "" },
        { id: "p-dad", name: "Owen Hale", aliases: [], relation: "", bio: "" },
        { id: "p-harper", name: "Harper Hale", aliases: [], relation: "", bio: "" },
      ],
      items: [
        {
          id: "email-1",
          title: "A big listing",
          date: "2001-02-07",
          date_precision: "exact",
          type: "document",
          people: [{ id: "p-mum" }, { id: "p-dad" }, { id: "p-harper" }, { id: "p-stranger" }, { id: "p-other" }],
          places: [],
          themes: [],
          assets: [],
        },
      ],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, st);
    const people = [...main.querySelectorAll(".block .chips .chip")].map((c) => c.textContent.trim());
    // only the attested spouse edge — the co-mentioned Harper/stranger/other do
    // not appear, even though the same item names them all
    expect(people).toEqual(["Owen Hale — husband"]);
  });

  it("splits Artifacts from Said by — complete and non-overlapping (2026-08-03)", () => {
    const letter = {
      id: "letter-1",
      title: "A letter",
      date: "1963-05-14",
      date_precision: "exact",
      type: "letter",
      people: [{ id: "p-alex" }],
      places: [],
      themes: [],
    };
    const told = {
      id: "story-1",
      title: "My own comment",
      date: "2026-08-02",
      date_precision: "exact",
      type: "story",
      told_by: "p-alex",
      people: [{ id: "p-alex" }],
      places: [],
      themes: [],
    };
    const toldAbout = {
      id: "story-2",
      title: "Another comment",
      date: "2026-08-02",
      date_precision: "exact",
      type: "story",
      told_by: "p-alex",
      people: [{ id: "p-owen" }],
      places: [],
      themes: [],
    };
    const main = document.createElement("main");
    const st = {
      ...STATE,
      people: [
        { id: "p-alex", name: "Alex Hale", aliases: [], relation: "", bio: "" },
        { id: "p-owen", name: "Owen Hale", aliases: [], relation: "", bio: "" },
      ],
      items: [letter, told, toldAbout],
      byId: new Map(),
    };
    personPage(main, { arg: "p-alex", query: new URLSearchParams() }, st);
    const text = main.textContent;
    expect(text).toContain("Artifacts with Alex Hale — 1");
    expect(text).toContain("Said by Alex Hale — 2");
    // the artifact appears once (Artifacts), the comments once each (Said by)
    expect(text.split("A letter").length - 1).toBe(1);
    expect(text.split("My own comment").length - 1).toBe(1);
    expect(text.split("Another comment").length - 1).toBe(1);
  });

  it("lists comments the person made under “Said by” (2026-08-03)", () => {
    const said = {
      id: "story-1",
      title: "The boat story",
      date: "2026-08-02",
      date_precision: "exact",
      type: "story",
      told_by: "p-mum",
      people: [{ id: "p-dad" }],
      places: [],
      themes: [],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, { ...STATE, items: [said], byId: new Map() });
    expect(main.textContent).toContain("Said by Nora Hale — 1");
    expect(main.textContent).toContain("The boat story");
  });

  it("renders relationship labels with the other person (TECH-SPEC §4)", () => {
    const st = {
      ...STATE,
      relationships: [
        { a: "p-mum", b: "p-dad", kind: "spouse", label_a: "husband", label_b: "wife" },
        { a: "p-mum", b: "p-alex", kind: "parent", label_a: "son", label_b: "mother" },
      ],
      people: [
        { id: "p-mum", name: "Nora Hale", aliases: [], relation: "", bio: "" },
        { id: "p-dad", name: "Owen Hale", aliases: [], relation: "", bio: "" },
        { id: "p-alex", name: "Alex Hale", aliases: [], relation: "", bio: "" },
      ],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, st);
    const related = [...main.querySelectorAll(".block .chips .chip")].map((c) => c.textContent.trim());
    expect(related).toContain("Owen Hale — husband");
    expect(related).toContain("Alex Hale — son");
  });
});

describe("person page involvement dates (2026-08-06)", () => {
  it("places a spanning item at the person's involvement date, not the item's", () => {
    const st = {
      ...STATE,
      items: [
        {
          id: "record",
          title: "Kendall–Pryce family record",
          date: "1868-03-20",
          date_precision: "exact",
          type: "document",
          people: [
            { id: "p-mum", date: { date: "1947-05-11", precision: "exact" } },
            { id: "p-dad", date: { date: "1868-03-20", precision: "exact" } },
          ],
          places: [],
          themes: [],
          assets: [],
        },
        {
          id: "letter-2",
          title: "A 1963 letter",
          date: "1963-05-14",
          date_precision: "exact",
          type: "letter",
          people: [{ id: "p-mum" }],
          places: [],
          themes: [],
          assets: [],
        },
      ],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, st);
    // the record's involvement is 1945 — it lands in the 1940s band, never
    // the 1860s (the decade list renders most recent first)
    const band = [...main.querySelectorAll("details.year")].find((b) =>
      b.querySelector(".year-number")?.textContent === "1940s",
    );
    expect(band.textContent).toContain("Kendall–Pryce family record");
    const sixties = [...main.querySelectorAll("details.year")].find((b) =>
      b.querySelector(".year-number")?.textContent === "1960s",
    );
    expect(sixties.textContent).toContain("A 1963 letter");
    expect(sixties.textContent).not.toContain("Kendall–Pryce family record");
  });
});

describe("proposed person marking (2026-08-06)", () => {
  it("marks a proposed person's page — the facts are a proposal, not record", () => {
    const state = {
      ...STATE,
      people: [
        {
          id: "p-proposed",
          name: "Pearl Whitlock",
          status: "proposed",
          dob: { date: "1912", precision: "year" },
          relation: "proposed sister-in-law",
        },
      ],
    };
    const main = document.createElement("main");
    personPage(main, { arg: "p-proposed", query: new URLSearchParams() }, { ...state, byId: new Map() });
    expect(main.textContent).toContain("Proposed — awaiting confirmation");
    expect(main.textContent).toContain("b. 1912");
  });

  it("leaves confirmed pages unmarked", () => {
    const main = document.createElement("main");
    personPage(main, { arg: "p-mum", query: new URLSearchParams() }, { ...STATE, byId: new Map() });
    expect(main.textContent).not.toContain("Proposed — awaiting confirmation");
  });
});

describe("the family tree's family membership (2026-08-06, user)", () => {
  const FAMILY_STATE = {
    people: [
      { id: "p-alf", name: "Ernie Draper", relation: "married Marta Voss, 1972" },
      { id: "p-pat", name: "Marta Voss" },
      { id: "p-richard", name: "Walter Lionel Draper" },
      { id: "p-robert", name: "Quentin Whitlock", relation: "Pearl's husband" },
      { id: "p-judith", name: "Pearl Whitlock" },
      { id: "p-stacey", name: "C. F. Wallace", relation: "Ministry of Supply official" },
    ],
    relationships: [
      { a: "p-alf", b: "p-pat", kind: "spouse", label_a: "spouse", label_b: "spouse" },
      { a: "p-alf", b: "p-richard", kind: "parent", label_a: "child", label_b: "parent" },
      { a: "p-robert", b: "p-judith", kind: "spouse", label_a: "spouse", label_b: "spouse" },
    ],
    items: [],
    places: [],
    themes: [],
    byId: new Map(),
  };

  it("never lists family members — anyone with a family edge — as 'Also in the archive'", () => {
    const main = document.createElement("main");
    render(main, {}, FAMILY_STATE);
    const others = [...main.querySelectorAll(".cast-relation")].map((r) => r.textContent);
    // Ernie (spouse of Marta), Walter (child of Ernie) and Quentin (spouse
    // of Pearl) are family; only the genuinely edgeless C. F. Wallace stays
    expect(others).toEqual(["Ministry of Supply official"]);
  });

  it("clamps long relations on the also-in-the-archive cards — no tall cards", () => {
    const state = {
      ...FAMILY_STATE,
      people: [
        ...FAMILY_STATE.people,
        { id: "p-stewartson", name: "Poppy Lindsay", relation: "niece, general servant — 'not sure where she fits in' (Pearl, 2001); connection unresolved" },
      ],
    };
    const main = document.createElement("main");
    render(main, {}, state);
    const relation = [...main.querySelectorAll(".cast-relation")].find((r) => r.textContent.includes("not sure where she fits"));
    expect(relation.classList.contains("clamp-2")).toBe(true);
  });
});
