import { describe, expect, it, vi } from "vitest";

// The router keeps module-level state (the in-app stack) — each test imports
// a FRESH module so the stack starts empty and the tests are independent
// (no cross-test pollution; the same pattern the review tests use for
// localStorage).
async function freshRouter() {
  vi.resetModules();
  return import("../router.js");
}

// happy-dom fires hashchange asynchronously; the test drives the real event
// synchronously instead of waiting on any timer — deterministic, no timers
const tick = () => {
  window.dispatchEvent(new Event("hashchange"));
};

describe("router", () => {
  it("parses the current hash into a route", async () => {
    const { parseHash } = await freshRouter();
    location.hash = "#/item/letter-1963-05-14";
    expect(parseHash()).toEqual({
      name: "item",
      arg: "letter-1963-05-14",
      rest: ["item", "letter-1963-05-14"],
      query: new URLSearchParams(),
    });
  });

  it("parses query strings", async () => {
    const { parseHash } = await freshRouter();
    location.hash = "#/search?q=migraine";
    const route = parseHash();
    expect(route.name).toBe("search");
    expect(route.query.get("q")).toBe("migraine");
  });

  it("navigate accepts both bare and hash-prefixed paths", async () => {
    const { navigate } = await freshRouter();
    navigate("place/pl-aldgate");
    expect(location.hash).toBe("#/place/pl-aldgate");
    navigate("#/place/pl-aldgate");
    expect(location.hash).toBe("#/place/pl-aldgate"); // no #/#/ double hash
  });

  it("goBack pops the in-app stack and never leaves the app", async () => {
    const { navigate, goBack, onRoute } = await freshRouter();
    onRoute(() => {});
    location.hash = "#/home";
    await tick(); // hashchange is async in happy-dom — let the stack catch up
    navigate("item/letter-1");
    await tick();
    navigate("person/p-mum");
    await tick();
    expect(location.hash).toBe("#/person/p-mum");
    goBack();
    await tick();
    expect(location.hash).toBe("#/item/letter-1");
    goBack();
    await tick();
    expect(location.hash).toBe("#/home");
    goBack(); // stack exhausted: stays inside the app regardless of prior state
    await tick();
    expect(location.hash.startsWith("#/")).toBe(true);
  });

  it("goBack from a first visit (fragment-less page) lands on #/home, never a blank URL", async () => {
    const { navigate, goBack, onRoute } = await freshRouter();
    onRoute(() => {});
    location.hash = ""; // fresh load: no hash fragment
    await tick();
    navigate("item/letter-1");
    await tick();
    expect(location.hash).toBe("#/item/letter-1");
    goBack(); // stack is ['', '#/item/letter-1'] — must fall back to home, not ''
    await tick();
    expect(location.hash).toBe("#/home");
  });

  it("goBack from a deep link goes UP to the logical parent, not home (PRD §8)", async () => {
    const { goBack, onRoute } = await freshRouter();
    location.hash = ""; // a fragment-less base — the stack starts empty
    onRoute(() => {});
    await tick();
    location.hash = "#/person/p-mum"; // a direct arrival — no in-app history
    await tick();
    goBack();
    await tick();
    expect(location.hash).toBe("#/cast"); // person's parent is the family tree
  });

  it("a place deep link goes UP to Places", async () => {
    const { goBack, onRoute } = await freshRouter();
    location.hash = "";
    onRoute(() => {});
    await tick();
    location.hash = "#/place/pl-marlock";
    await tick();
    goBack();
    await tick();
    expect(location.hash).toBe("#/places");
  });

  it("the review hub is a top-level door — its Up is home", async () => {
    const { goBack, onRoute } = await freshRouter();
    location.hash = "";
    onRoute(() => {});
    await tick();
    location.hash = "#/review";
    await tick();
    goBack();
    await tick();
    expect(location.hash).toBe("#/home");
  });

  it("the route handler's second argument marks a browser back/forward revisit", async () => {
    const { navigate, onRoute } = await freshRouter();
    location.hash = ""; // fragment-less base — the first render is not a revisit
    let seen = [];
    onRoute((ctx, revisit) => seen.push(revisit));
    seen = [];
    location.hash = "#/home";
    await tick();
    navigate("item/letter-1");
    await tick();
    navigate("person/p-mum");
    await tick();
    expect(seen).toEqual([false, false, false]); // each is a NEW page, not a revisit
    // browser back: the person hash is found earlier in the stack -> revisit
    history.back();
    await tick();
    expect(seen[seen.length - 1]).toBe(true);
    expect(location.hash).toBe("#/item/letter-1");
  });
});
