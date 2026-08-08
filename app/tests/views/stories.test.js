import { describe, expect, it } from "vitest";
import { render, themePage } from "../../views/stories.js";

const theme = { id: "t-the-boats", title: "The boats", subtitle: "Built on Iron Wharf", items: [] };
const storyItem = {
  id: "story-1",
  title: "The Grand Union",
  type: "story",
  date: "1964",
  date_precision: "year",
  recorded: "2026-08-03",
  story: "The curator: a memory.",
  told_by: "p-alex",
  themes: [{ id: "t-the-boats" }],
  people: [],
  places: [],
  assets: [],
};
const state = {
  items: [storyItem],
  people: [{ id: "p-alex", name: "Alex Hale" }],
  places: [],
  themes: [theme],
  byId: new Map([[storyItem.id, storyItem]]),
};

describe("theme page stories block", () => {
  it("renders stories told about the theme with the affordance", () => {
    const main = document.createElement("main");
    themePage(main, { arg: "t-the-boats", query: new URLSearchParams() }, state);
    // told accounts are MEMORIES, not "Stories" — the word the brother tripped on
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Memories about The boats",
    );
    expect(block.querySelector(".response-card .response-title").textContent).toBe("The Grand Union");
    expect(block.querySelector("button.btn").textContent).toBe("Add your memory to this theme");
  });

  it("shows the first-story hint when the theme has no stories yet", () => {
    const main = document.createElement("main");
    themePage(main, { arg: "t-the-boats", query: new URLSearchParams() }, { ...state, items: [], byId: new Map() });
    expect(main.textContent).toContain("No stories yet");
  });
});

describe("theme render-once (2026-08-06)", () => {
  it("a story curated into the theme's arrangement never repeats in Memories", () => {
    const arrangedTheme = { ...theme, items: [{ id: "story-1", note: "the boat years" }] };
    const main = document.createElement("main");
    themePage(main, { arg: "t-the-boats", query: new URLSearchParams() }, { ...state, themes: [arrangedTheme], byId: new Map([[storyItem.id, storyItem]]) });
    const cards = [...main.querySelectorAll(".card-title")].map((c) => c.textContent.trim());
    const block = [...main.querySelectorAll(".block")].find(
      (b) => b.querySelector(".block-title")?.textContent === "Memories about The boats",
    );
    // once, in the arrangement; the Memories block does not repeat it
    expect(cards.filter((t) => t === "The Grand Union").length).toBe(1);
    expect(block.textContent).toContain("No stories yet");
  });
});

describe("themes door naming (2026-08-06, Eli walk)", () => {
  it("heads the page 'Themes' — matching the door, not 'Stories'", () => {
    const main = document.createElement("main");
    render(main, {}, { items: [], themes: [], people: [], places: [], byId: new Map() });
    expect(main.querySelector("h1").textContent).toBe("Themes");
  });

  it("uses the plain-language description, not the librarian sentence", () => {
    const main = document.createElement("main");
    render(main, {}, { items: [], themes: [], people: [], places: [], byId: new Map() });
    expect(main.textContent).toContain("groups letters, photos and memories");
    expect(main.textContent).not.toContain("Themes are the doors");
  });
});

describe("theme list labels (2026-08-06, Eli walk)", () => {
  it("a seeded theme says 'the collection is still arriving' — never 'seeded'", () => {
    const main = document.createElement("main");
    render(
      main,
      {},
      {
        items: [],
        themes: [{ id: "t-x", title: "The music years", seeded: true, items: [] }],
        people: [],
        places: [],
        byId: new Map(),
      },
    );
    expect(main.textContent).toContain("0 items · the collection is still arriving");
    expect(main.textContent).not.toContain("seeded");
  });
});
