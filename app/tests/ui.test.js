import { describe, expect, it } from "vitest";
import { el, esc, itemCard } from "../ui.js";

describe("boolean form attrs (reviewer, 2026-08-03)", () => {
  it("checked: false sets the property, never a truthy attribute", () => {
    const box = el("input", { type: "checkbox", checked: false });
    expect(box.checked).toBe(false);
    expect(box.hasAttribute("checked")).toBe(false);
    const on = el("input", { type: "checkbox", checked: true });
    expect(on.checked).toBe(true);
  });

  it("disabled: false keeps the control enabled", () => {
    const btn = el("button", { disabled: false }, "Go");
    expect(btn.disabled).toBe(false);
  });
});

describe("ui primitives", () => {
  it("el builds a node with class, children and events", () => {
    const clicks = [];
    const node = el("button", { class: "chip", onclick: () => clicks.push(1) }, ["Hello", el("span", {}, "!")]);
    expect(node.tagName).toBe("BUTTON");
    expect(node.className).toBe("chip");
    expect(node.textContent).toBe("Hello!");
    node.click();
    expect(clicks).toHaveLength(1);
  });

  it("esc escapes text content", () => {
    expect(esc("<script>")).toBe("&lt;script&gt;");
  });

  it("el creates SVG elements in the SVG namespace", () => {
    const circle = el("circle", { r: 3 });
    expect(circle instanceof SVGElement).toBe(true);
    expect(circle.namespaceURI).toBe("http://www.w3.org/2000/svg");
  });

  it("el creates HTML anchors, not SVG ones — doors must lay out", () => {
    expect(el("a", { href: "#/home" }) instanceof HTMLAnchorElement).toBe(true);
    expect(el("svg:a", { href: "#/x" }) instanceof SVGElement).toBe(true);
  });

  it("itemCard shows the description line when present (2026-08-05)", () => {
    // A letter's description is what tells it apart from the rest of the
    // same correspondence on the timeline — it must render, not just exist
    // in the data.
    const withDesc = itemCard({ id: "l", title: "X", date: "1963-05-14", date_precision: "exact", type: "letter", description: "About the supersonic design, 1949." });
    expect(withDesc.querySelector(".card-desc").textContent).toBe("About the supersonic design, 1949.");
    const without = itemCard({ id: "l", title: "X", date: "1963-05-14", date_precision: "exact", type: "letter" });
    expect(without.querySelector(".card-desc")).toBeNull();
  });
});
