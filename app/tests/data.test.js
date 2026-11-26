import { afterEach, describe, expect, it, vi } from "vitest";
import { loadBootstrap } from "../data.js";

afterEach(() => vi.unstubAllGlobals());

describe("the bootstrap read", () => {
  it("surfaces the operator's remedy, not an internal status code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 503,
        json: async () => ({
          error: "the archive projection is not published",
          detail: "run loft publish",
        }),
      })),
    );
    await expect(loadBootstrap()).rejects.toThrow("run loft publish");
  });
});

describe("the private layer's refusal", () => {
  it("tells a signed-in stranger apart from nobody signed in", async () => {
    // 401 = nobody signed in (the sign-in gate); 403 = signed in, not family.
    // Both must never read as "the archive is empty".
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 403, json: async () => ({ error: "not on this archive's family list" }) })),
    );
    expect(await loadBootstrap()).toEqual({ signedIn: true, notAMember: true });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) })));
    expect(await loadBootstrap()).toEqual({ signedIn: false });
  });
});
