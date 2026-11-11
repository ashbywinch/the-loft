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

  it("the built boot bundle exists after setup", () => {
    // make setup builds app/dist; a missing bundle must fail here rather than
    // in a browser as a 404 for the shell's only script.
    expect(read("app/dist/boot.js").length).toBeGreaterThan(1000);
  });
});
