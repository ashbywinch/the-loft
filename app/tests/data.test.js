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
