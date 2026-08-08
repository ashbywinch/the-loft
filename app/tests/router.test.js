import { describe, expect, it } from "vitest";
import { parseHash, navigate, goBack, onRoute } from "../router.js";

// happy-dom fires hashchange asynchronously; the test drives the real event
// synchronously instead of waiting on any timer — deterministic, no timers
const tick = () => {
  window.dispatchEvent(new Event("hashchange"));
};

describe("router", () => {
  it("parses the current hash into a route", () => {
    location.hash = "#/item/letter-1963-05-14";
    expect(parseHash()).toEqual({ name: "item", arg: "letter-1963-05-14", query: new URLSearchParams() });
  });

  it("parses query strings", () => {
    location.hash = "#/search?q=migraine";
    const route = parseHash();
    expect(route.name).toBe("search");
    expect(route.query.get("q")).toBe("migraine");
  });

  it("navigate accepts both bare and hash-prefixed paths", () => {
    navigate("place/pl-aldgate");
    expect(location.hash).toBe("#/place/pl-aldgate");
    navigate("#/place/pl-aldgate");
    expect(location.hash).toBe("#/place/pl-aldgate"); // no #/#/ double hash
  });

  it("goBack pops the in-app stack and never leaves the app", async () => {
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
});
