import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchIdentity, NO_API } from "../app.js";
import { gateScreen } from "../gate.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the boot gate (2026-08-06)", () => {
  it("is a definitive 'not authenticated' that gates the archive", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ authenticated: false }),
        }),
      ),
    );
    expect(await fetchIdentity()).toBeNull();
  });

  it("passes a signed-in identity through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ authenticated: true, name: "Alex", person: "p-alex" }),
        }),
      ),
    );
    expect(await fetchIdentity()).toEqual({ authenticated: true, name: "Alex", person: "p-alex" });
  });

  it("treats a no-API static host as open only with an explicit opt-in", async () => {
    // a plain file server with no /api route at all (404/410) is a
    // genuinely no-API deployment — open
    for (const status of [404, 410]) {
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status, headers: new Headers() })));
      expect(await fetchIdentity()).toBe(NO_API);
    }
    // a static host that serves index.html for every route (200 non-JSON)
    // is ambiguous — open only when the deployment opts in explicitly
    const html = Promise.resolve({ ok: true, headers: new Headers({ "content-type": "text/html" }), json: async () => ({}) });
    vi.stubGlobal("fetch", vi.fn(() => html));
    expect(await fetchIdentity()).toBeNull(); // fail closed without the flag
    window.LOFT_NO_API = true;
    expect(await fetchIdentity()).toBe(NO_API); // opted in — open
    delete window.LOFT_NO_API;
  });

  it("fails closed when the auth server is unreachable, ambiguous, or says no — the archive never opens without a session", async () => {
    // network failure: the server is down — gate, never expose the archive
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("no server"))));
    expect(await fetchIdentity()).toBeNull();
    // a real server answering 401/403/500 is "not signed in" — gate
    for (const status of [401, 403, 500]) {
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status, headers: new Headers() })));
      expect(await fetchIdentity()).toBeNull();
    }
    // a 200 that is not JSON (proxy, SSO interstitial, captive portal) is
    // ambiguous — gate, unless the deployment explicitly opted in
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: true, headers: new Headers({ "content-type": "text/html" }), json: async () => ({}) })),
    );
    expect(await fetchIdentity()).toBeNull();
  });

  it("renders the sign-in gate, not content", () => {
    const main = gateScreen();
    expect(main.textContent).toContain("The Loft");
    expect(main.textContent).toContain("sign in");
    expect(main.querySelector("button").textContent).toBe("Sign in with Google");
  });
});
