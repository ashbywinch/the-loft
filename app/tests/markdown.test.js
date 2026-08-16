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

it("a leading pipe line without a separator is still verbatim — never dropped (2026-08-09 review)", () => {
    const nodes = renderMarkdown("| the boat's name |\n\nA line after.");
    expect(nodes).toHaveLength(2);
    expect(nodes[0].textContent).toBe("| the boat's name |");
    expect(nodes[1].textContent).toBe("A line after.");
  });

  it("two adjacent tables stay separate — the second is never swallowed (2026-08-11 review)", () => {
    const md =
      "| Name | Corps |\n|---|---|\n| BARLOW, Jack | R F A |\n" +
      "| Name | Rank |\n|---|---|\n| BARLOW, Harry | Pvt |";
    const nodes = renderMarkdown(md);
    expect(nodes).toHaveLength(2);
    expect(nodes[0].tagName).toBe("TABLE");
    expect(nodes[1].tagName).toBe("TABLE");
    expect([...nodes[0].querySelectorAll("tbody tr")]).toHaveLength(1);
    expect([...nodes[1].querySelectorAll("tbody tr")]).toHaveLength(1);
    expect(nodes[1].querySelector("tbody td").textContent).toBe("BARLOW, Harry"); // its own row, not a body row of table 1
  });

  it("the paragraphs carry the transcription-text class so the pre-line styling applies everywhere (2026-08-09 review)", () => {
    const nodes = renderMarkdown("Line one\nLine two");
    expect(nodes[0].className).toBe("transcription-text");
  });

  it("empty input produces no nodes", () => {
    expect(renderMarkdown("")).toHaveLength(0);
  });
});

describe("the inline format conventions — ~~struck~~ and ~underlined~ (2026-08-16)", () => {
  it("renders the strike and underline as spans, never literal tildes", () => {
    const nodes = renderMarkdown("a ~~crossed out~~ and ~underlined~ word");
    const p = nodes[0];
    expect(p.querySelector(".fmt-struck")?.textContent).toBe("crossed out");
    expect(p.querySelector(".fmt-underline")?.textContent).toBe("underlined");
    expect(p.textContent).toBe("a crossed out and underlined word");
  });

  it("leaves plain text untouched and the newlines intact", () => {
    const nodes = renderMarkdown("plain ~text~ here\nnext");
    expect(nodes[0].querySelector(".fmt-underline")?.textContent).toBe("text");
    expect(nodes[0].textContent).toBe("plain text here\nnext");
  });
});
