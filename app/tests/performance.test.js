import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(`${process.cwd()}/${path}`, "utf8");

describe("the front page's boot budget", () => {
  it("does not statically import the review surface", () => {
    const source = read("app/app.js");
    expect(source).not.toMatch(/^import[^;]*views\/review\.js/m);
    expect(source).toMatch(/import\("\.\/views\/review\.js"\)/);
  });

  it("does not load Leaflet on every page", () => {
    expect(read("app/index.html")).not.toContain("vendor/leaflet.js");
    expect(read("app/app.js")).toContain("loadLeaflet");
  });
});
