import { describe, expect, it } from "vitest";
import { render, defaultFocus, familyIds, familyGraph, pathTo } from "../../views/tree.js";

const STATE = {
  people: [
    { id: "p-miles", name: "Miles Hale" },
    { id: "p-vera", name: "Vera Hale" },
    { id: "p-dad", name: "Owen Hale" },
    { id: "p-mum", name: "Nora Hale" },
    { id: "p-alex", name: "Alex Hale" },
    { id: "p-hartley", name: "Mrs Hartley" },
  ],
  relationships: [
    { a: "p-miles", b: "p-vera", kind: "spouse", label_a: "spouse", label_b: "spouse" },
    { a: "p-miles", b: "p-dad", kind: "parent", label_a: "child", label_b: "parent" },
    { a: "p-vera", b: "p-dad", kind: "parent", label_a: "child", label_b: "parent" },
    { a: "p-mum", b: "p-dad", kind: "spouse", label_a: "spouse", label_b: "spouse" },
    { a: "p-mum", b: "p-alex", kind: "parent", label_a: "child", label_b: "parent" },
    { a: "p-dad", b: "p-alex", kind: "parent", label_a: "child", label_b: "parent" },
    { a: "p-alex", b: "p-hartley", kind: "teacher", label_a: "teacher", label_b: "pupil" },
  ],
};

const renderAt = (person, me = null) => {
  const main = document.createElement("main");
  render(main, { query: new URLSearchParams(person ? `person=${person}` : "") }, { ...STATE, me });
  return main;
};

describe("person-centred family tree (PRECEDENT.md §5)", () => {
  it("puts the focus person at the centre with parents above and children below", () => {
    const main = renderAt("p-dad");
    const roles = [...main.querySelectorAll(".tree-role")].map((r) => r.textContent.trim());
    expect(roles).toEqual(["Parents", "Children"]);
    expect(main.querySelector(".tree-centre .tree-focus .tree-name").textContent).toBe("Owen Hale");
    const parentBand = [...main.querySelectorAll(".tree-band")][0];
    expect(parentBand.textContent).toContain("Miles Hale");
    expect(parentBand.textContent).toContain("Vera Hale");
    const childBand = [...main.querySelectorAll(".tree-band")][1];
    expect(childBand.textContent).toContain("Alex Hale");
  });

  it("every card re-centres the tree; the focus card grows an explicit open button (2026-08-06)", () => {
    const main = renderAt("p-alex");
    // one action per card — the focus card is no longer a second kind of target
    const focusCard = main.querySelector(".tree-focus .tree-card");
    expect(focusCard.getAttribute("href")).toBe("#/tree?person=p-alex");
    const paul = [...main.querySelectorAll(".tree-card")].find((c) => c.textContent.includes("Owen Hale"));
    expect(paul.getAttribute("href")).toBe("#/tree?person=p-dad");
    // the open action is the button the focus card grows — never hidden
    const open = main.querySelector(".tree-focus .tree-open");
    expect(open).toBeTruthy();
    expect(open.getAttribute("href")).toBe("#/person/p-alex");
    expect(open.textContent).toBe("Open their page");
  });

  it("shows the partner beside the focus", () => {
    const main = renderAt("p-mum");
    const centre = [...main.querySelectorAll(".tree-centre .tree-card")].map((c) => c.textContent.trim());
    expect(centre.join(" | ")).toContain("Nora Hale");
    expect(centre.join(" | ")).toContain("Owen Hale");
  });

  it("shows wider relations (teacher, in-laws) below the centre", () => {
    const main = renderAt("p-alex");
    const rels = [...main.querySelectorAll(".tree-rel")].map((c) => c.textContent.trim());
    expect(rels).toContain("Mrs Hartley — teacher");
  });

  it("defaults the centre to the most-connected person", () => {
    expect(defaultFocus(STATE)).toBe("p-dad");
  });

  it("prefers the narrator when they are in the tree — never ancient history (2026-08-05)", () => {
    // defaultFocus(STATE) alone lands on the most-connected person, which with
    // a deep archive is a 19th-century hub nobody recognises. The narrator
    // ("you") is the sensible first centre; the most-connected is the fallback.
    expect(defaultFocus(STATE, "p-alex")).toBe("p-alex");
    expect(defaultFocus(STATE, "p-hartley")).toBe("p-dad"); // teacher — no family edge
  });

  it("the narrator is the signed-in person, never a claimed name (2026-08-06)", () => {
    const main = renderAt("p-alex", { person: "p-alex" });
    expect(main.querySelector(".tree-path")).toBeNull(); // you're home
  });

  it("opens on the narrator when the app knows who is using it", () => {
    const main = document.createElement("main");
    render(main, { query: new URLSearchParams() }, { ...STATE, me: { person: "p-alex" } });
    expect(main.querySelector(".tree-focus .tree-name").textContent).toBe("Alex Hale");
  });

  it("flags cards with links beyond the current view (2026-08-05)", () => {
    // Looking at ancient history, a card's family continues off-screen — the
    // card must say so. Owen has a spouse and a child that Miles's view
    // cannot show: "+2 more".
    const main = renderAt("p-miles");
    const paulCard = [...main.querySelectorAll(".tree-card")].find((c) => c.textContent.includes("Owen Hale"));
    expect(paulCard.textContent).toContain("+2 more");
    const ireneCard = [...main.querySelectorAll(".tree-card")].find((c) => c.textContent.includes("Vera Hale"));
    expect(ireneCard.textContent).not.toContain("more");
  });

  it("marks the person who leads back to the narrator (2026-08-05)", () => {
    // From Miles's generation the way back to Alex is through Owen — the
    // card must say so, and only that card.
    const main = renderAt("p-miles", { person: "p-alex" });
      const marked = [...main.querySelectorAll(".tree-card")].filter((c) =>
        c.textContent.includes("leads back to you"),
      );
      expect(marked).toHaveLength(1);
      expect(marked[0].textContent).toContain("Owen Hale");
  });

  it("the narrator's own view shows no back marker", () => {
    const main = renderAt("p-alex", { person: "p-alex" });
    expect(main.textContent).not.toContain("leads back to you");
  });

  it("falls back to the default centre when ?person= does not resolve", () => {
    const main = document.createElement("main");
    render(main, { query: new URLSearchParams("person=p-nobody") }, STATE);
    expect(main.querySelector(".tree-focus .tree-name").textContent).toBe("Owen Hale");
  });

  it("familyIds excludes people with no family edge", () => {
    expect(familyIds(STATE).has("p-hartley")).toBe(false);
    expect(familyIds(STATE).has("p-mum")).toBe(true);
  });
});

describe("tree card life lines (2026-08-06)", () => {
  it("shows dates on cards so same-name people differ", () => {
    const state = {
      people: [
        { id: "p-richard", name: "Walter Pryce", dob: { date: "1783", precision: "exact" }, dod: { date: "1862", precision: "approx" } },
        { id: "p-harper-sr", name: "Harper Pryce", dob: { date: "1790", precision: "approx" } },
        { id: "p-harper", name: "Harper Pryce", dob: { date: "1830-05-03", precision: "exact" } },
      ],
      relationships: [
        { a: "p-richard", b: "p-harper-sr", kind: "spouse" },
        { a: "p-richard", b: "p-harper", kind: "parent" },
      ],
    };
    const main = document.createElement("main");
    render(main, { query: new URLSearchParams("person=p-richard") }, state);
    const years = [...main.querySelectorAll(".tree-years")].map((y) => y.textContent);
    expect(years).toContain("1783–circa 1862");
    expect(years).toContain("b. circa 1790");
    expect(years).toContain("b. 1830");
  });

  it("leaves date-less cards without a life line", () => {
    const main = document.createElement("main");
    render(main, { query: new URLSearchParams("person=p-dad") }, STATE);
    expect(main.querySelectorAll(".tree-years").length).toBe(0);
  });
});

describe("the path to you (2026-08-06)", () => {
  it("shows the route from the focus to the narrator; hops re-centre, the endpoint opens the record", () => {
    const main = renderAt("p-miles", { person: "p-alex" });
    {
      const bar = main.querySelector(".tree-path");
      expect(bar).toBeTruthy();
      expect(bar.textContent).toContain("Miles Hale");
      expect(bar.textContent).toContain("Owen Hale");
      expect(bar.textContent).toContain("Alex Hale");
      const you = bar.querySelector(".tree-path-you");
      expect(you.getAttribute("href")).toBe("#/person/p-alex");
      // the focus is the current page (plain), Owen is the one hop
      const hop = [...bar.querySelectorAll(".tree-path-hop")][0];
      expect(hop.textContent).toBe("Owen Hale");
      expect(hop.getAttribute("href")).toBe("#/tree?person=p-dad");
      expect(bar.querySelector(".tree-path-current").textContent).toBe("Miles Hale");
    }
  });

  it("hides the bar when the narrator is the focus — you're home", () => {
    const main = renderAt("p-alex", { person: "p-alex" });
    expect(main.querySelector(".tree-path")).toBeNull();
  });

  it("truncates a path longer than five hops to first + ellipsis + last two", () => {
    const chain = ["p-a", "p-b", "p-c", "p-d", "p-e", "p-f", "p-g", "p-h"];
    const state = {
      people: chain.map((id) => ({ id, name: id.toUpperCase() })),
      relationships: chain.slice(0, -1).map((id, i) => ({ a: id, b: chain[i + 1], kind: "parent" })),
    };
    const main = document.createElement("main");
    render(main, { query: new URLSearchParams("person=p-a") }, { ...state, me: { person: "p-h" } });
    const bar = main.querySelector(".tree-path");
    const hops = [...bar.querySelectorAll(".tree-path-hop")].map((a) => a.textContent);
    expect(hops).toEqual(["P-G"]); // only the second-last survives; the middle collapses
    expect(bar.querySelector(".tree-path-current").textContent).toBe("P-A");
    expect(bar.textContent).toContain("…");
    expect(bar.querySelector(".tree-path-you").textContent).toBe("P-H");
  });
});

describe("proposed people are not family until confirmed (2026-08-07, user)", () => {
  // p-proposed is the ONLY link between p-dad and p-mum — the graph must not
  // place or route through an unconfirmed identity
  const onlyThroughProposed = () => ({
    people: [
      { id: "p-dad", name: "Owen Hale" },
      { id: "p-mum", name: "Nora Hale" },
      { id: "p-proposed", name: "Proposed Person", status: "proposed" },
    ],
    relationships: [
      { a: "p-dad", b: "p-proposed", kind: "spouse", label_a: "spouse", label_b: "spouse" },
      { a: "p-proposed", b: "p-mum", kind: "spouse", label_a: "spouse", label_b: "spouse" },
    ],
  });

  it("familyIds excludes a proposed person even with a family edge", () => {
    expect(familyIds(onlyThroughProposed()).has("p-proposed")).toBe(false);
  });

  it("familyGraph never links a proposed person — pathTo cannot route through one", () => {
    const graph = familyGraph(onlyThroughProposed());
    expect(graph.has("p-proposed")).toBe(false);
    expect(pathTo(graph, "p-dad", "p-mum")).toBeNull();
  });

  it("the tree never renders a proposed relative", () => {
    const main = document.createElement("main");
    render(main, { query: new URLSearchParams("person=p-dad") }, onlyThroughProposed());
    expect(main.textContent).not.toContain("Proposed Person");
  });
});
