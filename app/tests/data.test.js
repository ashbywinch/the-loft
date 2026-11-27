import { afterEach, describe, expect, it, vi } from "vitest";
import { documentsToReview, loadBootstrap } from "../data.js";

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

describe("the front door's transcripts count", () => {
  it("counts the documents whose row check is part-done", () => {
    // the hub lists a part-checked document under documents_partial: its
    // checked pages are already reviewable, so counting only the fully
    // checked ones made a half-checked batch contribute nothing
    const batches = [
      { status: "review", documents_ready: [0], documents_partial: [1, 2] },
      { status: "confirmed", documents_ready: [3], documents_partial: [4] },
    ];
    expect(documentsToReview(batches)).toBe(3);
  });
});
