import { afterEach, describe, expect, it } from "vitest";
import { render } from "../../views/item.js";

const makeItem = (overrides = {}) => ({
  id: "item-x",
  title: "An item",
  date: "1963-05-14",
  date_precision: "exact",
  type: "letter",
  assets: [],
  ...overrides,
});

const state = (items) => ({
  items,
  people: [],
  places: [],
  themes: [],
  byId: new Map(items.map((item) => [item.id, item])),
});

describe("draft privacy (review, 2026-08-03: the banner's claim must be true)", () => {
  afterEach(() => localStorage.clear());

  const draftItem = () =>
    makeItem({
      id: "story-d1",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      description: "The private what-is-this line.",
      story: "The secret half-told account.",
      recorded: "2026-08-03",
      people: [{ id: "p-alex", status: "proposed" }],
      places: [],
      themes: [],
      items: [],
    });
  const peopleState = (items) => ({
    ...state(items),
    people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
  });

  it("a visitor who is not the narrator sees the banner but never the account", () => {
    const main = document.createElement("main");
    render(main, { arg: "story-d1", query: new URLSearchParams() }, peopleState([draftItem()]));
    expect(main.textContent).toContain("Unfinished");
    expect(main.textContent).not.toContain("The secret half-told account"); // the unverified words stay hidden
    expect(main.textContent).not.toContain("The secret half-told"); // the title stays hidden too (reviewer, 2026-08-03)
    expect(main.textContent).not.toContain("The private what-is-this line."); // the description too (reviewer, 2026-08-07)
    expect(main.textContent).not.toContain("Details");
  });

  it("the narrator who claimed it sees the account and the Continue action", () => {
    const main = document.createElement("main");
    render(main, { arg: "story-d1", query: new URLSearchParams() }, { ...peopleState([draftItem()]), me: { person: "p-alex" } });
    expect(main.textContent).toContain("The secret half-told account");
    expect(main.textContent).toContain("The private what-is-this line."); // the narrator sees the description too
    expect([...main.querySelectorAll("button")].some((b) => b.textContent.includes("Continue this story"))).toBe(true);
  });
});

describe("item view", () => {
  it("renders a scans-pending caption and no image when the item has no assets", () => {
    const main = document.createElement("main");
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([makeItem()]));
    expect(main.querySelector("img.lens-img")).toBeNull();
    expect(main.querySelector(".lens-caption").textContent).toContain("No scans yet");
    // an empty src would make the browser request the page URL — never render one
    expect(main.querySelector('.lens-img[src=""]')).toBeNull();
  });

  it("renders the first asset image when one exists", () => {
    const main = document.createElement("main");
    const item = makeItem({ assets: [{ kind: "page", file: "page-1.svg", caption: "Page 1" }] });
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([item]));
    const img = main.querySelector("img.lens-img");
    expect(img).toBeTruthy();
    expect(img.getAttribute("src")).toBe("data/assets/item-x/page-1.svg");
  });

  it("resolves detail chips from the passed state, not the data module singleton", () => {
    const main = document.createElement("main");
    const item = makeItem({
      people: [{ id: "p-mum" }],
      places: [{ id: "pl-aldgate" }],
      themes: [{ id: "t-music" }],
    });
    const st = state([item]);
    st.people = [{ id: "p-mum", name: "Nora Hale" }];
    st.places = [{ id: "pl-aldgate", name: "Aldgate" }];
    st.themes = [{ id: "t-music", title: "The music years" }];
    render(main, { arg: "item-x", query: new URLSearchParams() }, st);
    const chips = [...main.querySelectorAll(".chips-inline .chip")].map((c) => c.textContent.trim());
    expect(chips).toEqual(expect.arrayContaining(["Nora Hale", "Aldgate", "The music years"]));
    expect(chips.some((c) => c.includes("p-mum") || c.includes("pl-") || c.includes("t-"))).toBe(false);
  });

  it("marks vision-read transcriptions as drafts (TECH-SPEC §16.7)", () => {
    const main = document.createElement("main");
    const item = makeItem({ transcription: "Some machine-read text", transcription_status: "draft" });
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([item]));
    const toggle = [...main.querySelectorAll("button.toggle")].find((b) => /read/i.test(b.textContent));
    expect(toggle.textContent).toBe("Read the draft");
    toggle.click();
    expect(main.querySelector(".draft-note").textContent).toContain("not yet verified");
    expect(main.querySelector(".transcription-text").textContent).toBe("Some machine-read text");
  });

  it("labels a story item as Memory in the Type row (2026-08-03)", () => {
    const main = document.createElement("main");
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([makeItem({ type: "story" })]));
    const dd = [...main.querySelectorAll(".details div")]
      .find((d) => d.querySelector("dt")?.textContent === "Type")
      ?.querySelector("dd");
    expect(dd?.textContent).toBe("Memory");
  });

  it("never surfaces a sensitive item in Nearby in the archive (PRD §6, 2026-08-03)", () => {
    const main = document.createElement("main");
    const item = makeItem({ people: [{ id: "p-nora" }] });
    const sensitive = makeItem({
      id: "doc-sensitive",
      title: "A sensitive document",
      type: "document",
      people: [{ id: "p-nora" }],
      sensitive: true,
    });
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([item, sensitive]));
    expect(main.textContent).not.toContain("A sensitive document");
  });

  it("renders Details before Responses — facts first, others' commentary last (PRD §19.7)", () => {
    const main = document.createElement("main");
    const item = makeItem();
    const resp = makeItem({ id: "resp-1", title: "A response", type: "story", comment_on: "item-x" });
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([item, resp]));
    const titles = [...main.querySelectorAll(".block-title")].map((t) => t.textContent);
    expect(titles.indexOf("Details")).toBeGreaterThan(-1);
    expect(titles.indexOf("Responses")).toBeGreaterThan(titles.indexOf("Details"));
  });

  it("renders dated, attributed responses on the commented item (§4 comment_on)", () => {
    const letter = makeItem({ id: "letter-1977", title: "The new bath", date: "1977-01-12" });
    const comment = {
      id: "story-ann",
      title: "Harper's account of 1977",
      date: "2026-06-30",
      date_precision: "exact",
      type: "story",
      story: "It was not a nervous breakdown.",
      told_by: "p-jude",
      comment_on: "letter-1977",
      people: [{ id: "p-jude" }],
    };
    const st = state([letter, comment]);
    st.people = [{ id: "p-jude", name: "Jude Hale" }];
    const main = document.createElement("main");
    render(main, { arg: "letter-1977", query: new URLSearchParams() }, st);
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Responses",
    );
    expect(block.textContent).toContain("Harper's account of 1977");
    expect(block.textContent).toContain("Jude Hale");
    expect(block.textContent).toContain("It was not a nervous breakdown.");
  });

  it("shows what a comment responds to", () => {
    const letter = makeItem({ id: "letter-1977", title: "The new bath", date: "1977-01-12" });
    const comment = {
      id: "story-ann",
      title: "Harper's account of 1977",
      date: "2026-06-30",
      date_precision: "exact",
      type: "story",
      story: "It was not a nervous breakdown.",
      told_by: "p-jude",
      comment_on: "letter-1977",
      people: [{ id: "p-jude" }],
    };
    const main = document.createElement("main");
    render(main, { arg: "story-ann", query: new URLSearchParams() }, state([letter, comment]));
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "In response to",
    );
    expect(block.querySelector("a").textContent).toBe("The new bath");
    expect(block.querySelector("a").getAttribute("href")).toBe("#/item/letter-1977");
  });

  it("orders nearby items by date proximity, not chronology", () => {
    const main = document.createElement("main");
    const current = makeItem({ id: "item-1977", title: "Now", date: "1977-01-01", people: [{ id: "p-mum" }] });
    const others = [
      {
        id: "item-1963",
        title: "Old",
        date: "1963-01-01",
        date_precision: "exact",
        type: "letter",
        people: [{ id: "p-mum" }],
      },
      {
        id: "item-1976",
        title: "Closer",
        date: "1976-06-01",
        date_precision: "exact",
        type: "letter",
        people: [{ id: "p-mum" }],
      },
      { id: "item-1978", title: "Next", date: "1978-01-01", date_precision: "exact", type: "letter" },
    ];
    render(main, { arg: "item-1977", query: new URLSearchParams() }, state([current, ...others]));
    const titles = [...main.querySelectorAll(".block .card-grid .card-title")].map((c) => c.textContent);
    expect(titles).toEqual(["Closer", "Next", "Old"]);
  });

  it("resets zoom when switching assets", () => {
    const main = document.createElement("main");
    const item = makeItem({
      assets: [
        { kind: "page", file: "page-1.svg", caption: "Page 1" },
        { kind: "page", file: "page-2.svg", caption: "Page 2" },
      ],
    });
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([item]));
    const img = main.querySelector("img.lens-img");
    const btn = (label) =>
      [...main.querySelectorAll(".btn, .lens-btn, .toggle")].find((b) => b.textContent.includes(label));
    img.click(); // zoom in
    expect(img.classList.contains("zoomed")).toBe(true);
    btn("Next").click();
    expect(img.getAttribute("src")).toBe("data/assets/item-x/page-2.svg");
    expect(img.classList.contains("zoomed")).toBe(false);
    expect(btn("🔍").textContent).toBe("🔍 Zoom");
  });

  it("lists dated, attributed story responses under the item", () => {
    const main = document.createElement("main");
    const resp = {
      id: "story-1",
      title: "The flat search",
      type: "story",
      date: "1963-05",
      date_precision: "month",
      recorded: "2026-08-03",
      story: "The curator: a memory.",
      told_by: "p-mum",
      comment_on: "item-x",
      people: [],
      places: [],
      themes: [],
      assets: [],
    };
    const st = state([makeItem(), resp]);
    st.people = [{ id: "p-mum", name: "Nora Hale" }];
    render(main, { arg: "item-x", query: new URLSearchParams() }, st);
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Responses",
    );
    expect(block.querySelector(".response-card .response-title").textContent).toBe("The flat search");
    expect(block.querySelector(".response-card .card-meta").textContent).toBe(
      "Told by Nora Hale · May 1963 · told 3 Aug 2026",
    );
    expect(block.querySelector("button.btn").textContent).toBe("Add your memory");
  });

  it("links a story back to the artifact it responds to", () => {
    const main = document.createElement("main");
    const letter = makeItem({ id: "letter-x", title: "A week in the flat" });
    const storyItem = makeItem({ id: "story-1", type: "story", title: "The flat search", comment_on: "letter-x" });
    render(main, { arg: "story-1", query: new URLSearchParams() }, state([letter, storyItem]));
    const link = [...main.querySelectorAll(".block a.reader-open")].find((a) => a.textContent === "A week in the flat");
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("#/item/letter-x");
  });

  it("offers the affordance even before any responses exist", () => {
    const main = document.createElement("main");
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([makeItem()]));
    expect(main.textContent).toContain("No stories yet");
    expect(main.querySelector("button.btn")).toBeTruthy();
  });

  it("renders a story account with attribution, dates, and paragraph breaks", () => {
    const main = document.createElement("main");
    const storyItem = makeItem({
      id: "story-1",
      type: "story",
      title: "The trips",
      date: "1963-05",
      date_precision: "month",
      recorded: "2026-08-03",
      story: "Para one.\n\nQ: When?\nA: May.",
      told_by: "p-mum",
      assets: [],
    });
    const st = state([storyItem]);
    st.people = [{ id: "p-mum", name: "Nora Hale" }];
    render(main, { arg: "story-1", query: new URLSearchParams() }, st);
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "The account",
    );
    expect(block.querySelectorAll("p.story").length).toBe(2); // paragraph breaks survive
    expect(block.querySelector(".card-meta").textContent).toBe("Told by Nora Hale · May 1963 · recorded 2026-08-03");
  });

  it("renders artifact chips and lists item-linked stories as responses", () => {
    const boat = makeItem({ id: "object-sunlight", title: "Sunlight", type: "object" });
    const storyItem = makeItem({
      id: "story-1",
      type: "story",
      title: "Sailing",
      date: "1980",
      date_precision: "year",
      story: "We sailed.",
      told_by: "p-mum",
      items: [{ id: "object-sunlight" }],
      assets: [],
    });
    const st = state([boat, storyItem]);
    st.people = [{ id: "p-mum", name: "Nora Hale" }];

    // the story page shows the artifact chip in its details
    const main = document.createElement("main");
    render(main, { arg: "story-1", query: new URLSearchParams() }, st);
    const details = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Details",
    );
    expect(details.textContent).toContain("Sunlight");

    // the artifact's page lists the story in Referenced by — an items ref
    // is an attestation, not a response (2026-08-06, render-once)
    const main2 = document.createElement("main");
    render(main2, { arg: "object-sunlight", query: new URLSearchParams() }, st);
    const responses = [...main2.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Responses",
    );
    expect(responses.textContent).not.toContain("Sailing");
    const refs = [...main2.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Referenced by",
    );
    expect(refs.textContent).toContain("Sailing");
  });
});

describe("draft exposure (user, 2026-08-03: a draft is for the person who claimed it)", () => {
  afterEach(() => {
    localStorage.clear();
  });

  const draft = () =>
    makeItem({
      id: "story-d1",
      type: "story",
      status: "draft",
      told_by: "p-alex",
      story: "The Mirosa was moored alongside.",
      recorded: "2026-08-03",
      people: [{ id: "p-alex", status: "proposed" }],
      places: [],
      themes: [],
      items: [],
    });
  const withPeople = (items) => ({
    ...state(items),
    people: [{ id: "p-alex", name: "Alex Hale", aliases: ["Alex"] }],
  });

  it("shows the draft banner with Continue for the person who claimed it", () => {
    const main = document.createElement("main");
    render(main, { arg: "story-d1", query: new URLSearchParams() }, { ...withPeople([draft()]), me: { person: "p-alex" } });
    expect(main.textContent).toContain("Unfinished");
    const continueBtn = [...main.querySelectorAll("button")].find((b) => b.textContent.includes("Continue this story"));
    expect(continueBtn).toBeTruthy();
  });

  it("shows the banner without Continue for anyone else", () => {
    const main = document.createElement("main");
    render(main, { arg: "story-d1", query: new URLSearchParams() }, { ...withPeople([draft()]), me: { person: "p-other" } });
    expect(main.textContent).toContain("Unfinished");
    const continueBtn = [...main.querySelectorAll("button")].find((b) => b.textContent.includes("Continue this story"));
    expect(continueBtn).toBeUndefined();
  });
});

describe("item description", () => {
  it("renders the description under the title (2026-08-05)", () => {
    const main = document.createElement("main");
    render(
      main,
      { arg: "item-x", query: new URLSearchParams() },
      state([makeItem({ description: "The Ministry's reply to the design submission, 1949." })]),
    );
    const text = main.textContent;
    expect(text).toContain("The Ministry's reply to the design submission, 1949.");
    expect(text.indexOf("The Ministry's reply")).toBeGreaterThan(text.indexOf("An item"));
  });

  it("renders nothing when there is no description", () => {
    const main = document.createElement("main");
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([makeItem()]));
    expect(main.textContent).not.toContain("description");
  });
});

describe("item clarification fragments", () => {
  it("shows a clarification fragment that attests the item, in its own block", () => {
    const clar = {
      id: "c-winch",
      title: "The Hale family",
      date: "2026-08-02",
      date_precision: "exact",
      type: "story",
      clarification: true,
      told_by: "p-alex",
      recorded: "2026-08-03",
      story: "Harper is Harper Hale, she married Owen's brother Dale Hale.",
      people: [],
      items: [{ id: "item-x" }],
      themes: [],
      assets: [],
    };
    const main = document.createElement("main");
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([makeItem(), clar]));
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Clarifications",
    );
    expect(block).toBeTruthy();
    expect(block.textContent).toContain("Harper is Harper Hale");
  });
});

describe("item sources", () => {
  it("renders web sources as hyperlinks with their access dates (2026-08-06)", () => {
    const main = document.createElement("main");
    render(
      main,
      { arg: "item-x", query: new URLSearchParams() },
      state([
        makeItem({
          provenance: "The Upper Eden History Society's pages.",
          sources: [{ url: "https://www.upperedenhistory.org.uk/BluePlaques/bp6.htm", accessed: "2026-08-05" }],
        }),
      ]),
    );
    const link = main.querySelector('a[href="https://www.upperedenhistory.org.uk/BluePlaques/bp6.htm"]');
    expect(link).toBeTruthy();
    expect(link.textContent).toContain("www.upperedenhistory.org.uk");
    expect(main.textContent).toContain("accessed 2026-08-05");
  });
});

describe("item back links (2026-08-06)", () => {
  it("shows the items that reference this one — all links are bidirectional", () => {
    const story = {
      id: "story-1",
      title: "The boat story",
      type: "story",
      date: "1980",
      date_precision: "year",
      recorded: "2026-08-03",
      story: "We launched the boats.",
      told_by: "p-alex",
      people: [],
      places: [],
      themes: [],
      items: [{ id: "item-x" }],
      assets: [],
    };
    const main = document.createElement("main");
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([makeItem(), story]));
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Referenced by",
    );
    expect(block).toBeTruthy();
    expect(block.querySelector("a").textContent).toContain("The boat story");
  });
});

describe("item responses vs referenced-by (2026-08-06)", () => {
  it("an items-ref story renders once — in Referenced by, never in Responses", () => {
    const attesting = {
      id: "story-1",
      title: "The boat story",
      type: "story",
      date: "1980",
      date_precision: "year",
      recorded: "2026-08-03",
      story: "We launched the boats.",
      told_by: "p-alex",
      people: [],
      places: [],
      themes: [],
      items: [{ id: "item-x" }],
      assets: [],
    };
    const main = document.createElement("main");
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([makeItem(), attesting]));
    const titles = [...main.querySelectorAll(".block-title")].map((t) => t.textContent);
    expect(titles).toContain("Referenced by");
    const responses = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Responses",
    );
    expect(responses.textContent).not.toContain("The boat story"); // the empty-state block remains
    const refs = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Referenced by",
    );
    expect(refs.textContent).toContain("The boat story");
  });
});

describe("response-with-items-ref renders once (2026-08-06)", () => {
  it("an item that is both a response and an items-ref appears only in Responses", () => {
    const both = {
      id: "story-2",
      title: "The response that also refs",
      type: "story",
      date: "1981",
      date_precision: "year",
      recorded: "2026-08-03",
      story: "About this letter.",
      told_by: "p-alex",
      people: [],
      places: [],
      themes: [],
      comment_on: "item-x",
      items: [{ id: "item-x" }],
      assets: [],
    };
    const main = document.createElement("main");
    render(main, { arg: "item-x", query: new URLSearchParams() }, state([makeItem(), both]));
    const titles = [...main.querySelectorAll(".block-title")].map((t) => t.textContent);
    expect(titles).not.toContain("Referenced by"); // the block is absent entirely
    const responses = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Responses",
    );
    expect(responses.textContent).toContain("The response that also refs");
  });
});
