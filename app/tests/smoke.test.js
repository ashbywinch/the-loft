import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { render as home } from "../views/home.js";
import { render as timeline } from "../views/timeline.js";
import { render as item } from "../views/item.js";
import { render as cast, personPage } from "../views/cast.js";
import { render as tree } from "../views/tree.js";
import { render as places, placePage } from "../views/places.js";
import { render as stories, themePage, reader } from "../views/stories.js";
import { render as museum } from "../views/museum.js";
import { render as letters } from "../views/letters.js";
import { render as search } from "../views/search.js";
import { render as curator } from "../views/curator.js";
import { render as importReview } from "../views/import.js";

const REPO = `${process.cwd()}/`;

/** The real projection — a view that crashes on the actual data is a blank
 *  page in the app (the-loft 2026-08-08: the import review went blank after
 *  a rework; the view tests used fixtures, so no suite caught it). */
function realState() {
  const index = JSON.parse(readFileSync(`${REPO}app/data/index.json`, "utf8"));
  const people = JSON.parse(readFileSync(`${REPO}app/data/people.json`, "utf8"));
  const places = JSON.parse(readFileSync(`${REPO}app/data/places.json`, "utf8"));
  const themes = JSON.parse(readFileSync(`${REPO}app/data/themes.json`, "utf8"));
  const transcripts = JSON.parse(readFileSync(`${REPO}app/data/transcripts.json`, "utf8"));
  const imports = JSON.parse(readFileSync(`${REPO}app/data/imports.json`, "utf8"));
  return {
    items: index.items,
    people: people.people,
    places: places.places,
    themes: themes.themes,
    relationships: people.relationships ?? [],
    imports: imports.imports ?? [],
    transcripts,
    byId: new Map(index.items.map((item) => [item.id, item])),
    me: { person: "p-alex" },
  };
}

const hasData = (() => {
  try {
    readFileSync(`${REPO}app/data/index.json`, "utf8");
    return true;
  } catch {
    return false;
  }
})();

const ctx = (over = {}) => ({ arg: null, query: new URLSearchParams(), ...over });

const ROUTES = [
  ["home", home, ctx()],
  ["timeline", timeline, ctx()],
  ["cast", cast, ctx()],
  ["tree", tree, ctx()],
  ["places", places, ctx()],
  ["themes", stories, ctx()],
  ["museum", museum, ctx()],
  ["letters", letters, ctx()],
  ["search", search, ctx({ query: new URLSearchParams("q=") })],
  ["curator", curator, ctx()],
  ["import", importReview, ctx({ arg: "import-documents" })],
];

describe.skipIf(!hasData)("every view renders on the real projection (2026-08-08: a blank page is a view crashing on the actual data)", () => {
  it.each(ROUTES)("renders %s", (_name, render, ctx) => {
    const main = document.createElement("main");
    render(main, ctx, realState());
    expect(main.childElementCount).toBeGreaterThan(0); // never a blank render
  });

  it.each([cast, places, stories, importReview])("renders %s detail pages for real ids", (render) => {
    const state = realState();
    const personId = state.people[0]?.id;
    const placeId = state.places[0]?.id;
    const themeId = state.themes[0]?.id;
    const itemId = state.items[0]?.id;
    const cases = [
      [personPage, ctx({ arg: personId })],
      [placePage, ctx({ arg: placeId })],
      [themePage, ctx({ arg: themeId })],
      [reader, ctx({ arg: itemId })],
    ];
    for (const [fn, ctx] of cases) {
      if (!ctx.arg) continue;
      const main = document.createElement("main");
      fn(main, ctx, state);
      expect(main.childElementCount).toBeGreaterThan(0);
    }
  });
});
