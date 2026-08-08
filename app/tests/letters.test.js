import { describe, expect, it } from "vitest";
import { render } from "../views/letters.js";
import { typeLabel } from "../data.js";

describe("the told-vs-scanned distinction (user, 2026-08-03: his brother looked for the letters)", () => {
  it('a told account displays as a "Memory", never a "Story"', () => {
    expect(typeLabel("story")).toBe("Memory");
    expect(typeLabel("letter")).toBe("Letter");
  });

  it("the Letters surface shows only the scanned written material, decade-banded", () => {
    const items = [
      {
        id: "letter-1963-05-14",
        title: "A week in the flat",
        date: "1963-05-14",
        date_precision: "exact",
        type: "letter",
        assets: [],
      },
      { id: "doc-1964", title: "A rent book", date: "1964", date_precision: "year", type: "document", assets: [] },
      { id: "photo-1", title: "The shared flat", date: "1965", date_precision: "year", type: "photo", assets: [] },
      // a told memory is NOT written material — it must not appear here
      {
        id: "story-1",
        title: "The Grand Union",
        date: "1964",
        date_precision: "year",
        type: "story",
        recorded: "2026-08-03",
        assets: [],
        told_by: "p-alex",
      },
    ];
    const main = document.createElement("main");
    render(main, {}, { items, people: [], places: [], themes: [], byId: new Map(items.map((i) => [i.id, i])) });
    expect(main.textContent).toContain("A week in the flat");
    expect(main.textContent).toContain("A rent book");
    expect(main.textContent).not.toContain("The Grand Union");
    expect(main.textContent).not.toContain("The shared flat"); // photos live on the timeline, not the letters shelf
  });
});
