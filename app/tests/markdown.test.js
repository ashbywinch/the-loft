import { describe, expect, it } from "vitest";
import { renderMarkdown } from "../markdown.js";

describe("the transcription markdown renderer (2026-08-08: a medal index card is a table — the site must render it as one, not a run-on paragraph)", () => {
  it("renders a pipe table with a header and body rows", () => {
    const md = "| Name | Corps | Remarks |\n|---|---|---|\n| BARLOW, Jack | R F A | Dead |\n| BARLOW, Harry | Lan. Fus | do |";
    const nodes = renderMarkdown(md);
    expect(nodes).toHaveLength(1);
    const table = nodes[0];
    expect(table.tagName).toBe("TABLE");
    expect([...table.querySelectorAll("th")].map((t) => t.textContent)).toEqual(["Name", "Corps", "Remarks"]);
    expect([...table.querySelectorAll("tbody tr")]).toHaveLength(2);
    expect(table.querySelector("tbody td").textContent).toBe("BARLOW, Jack");
  });

  it("leaves plain text as paragraphs with the newlines intact", () => {
    const nodes = renderMarkdown("Line one\nLine two\n\nLine three");
    expect(nodes).toHaveLength(2);
    expect(nodes[0].tagName).toBe("P");
    expect(nodes[0].textContent).toBe("Line one\nLine two");
    expect(nodes[1].textContent).toBe("Line three");
  });

  it("a lone pipe line without a separator is not a table — it stays a paragraph", () => {
    const nodes = renderMarkdown("just | a | line");
    expect(nodes).toHaveLength(1);
    expect(nodes[0].tagName).toBe("P");
    expect(nodes[0].textContent).toBe("just | a | line");
  });

  it("empty input produces no nodes", () => {
    expect(renderMarkdown("")).toHaveLength(0);
  });
});
