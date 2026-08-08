import { describe, expect, it } from "vitest";
import { linkMentions, mentionMatches } from "../people.js";

const PEOPLE = [
  { id: "p-mum", name: "Nora Hale", aliases: ["Mum", "Mummy", "Nora"] },
  { id: "p-dad", name: "Owen Hale", aliases: ["Dad", "Daddy", "Owen"] },
  { id: "p-grandmother", name: "Fern Voss", aliases: ["Mother", "Mama", "Grandmother", "Nana", "Fern"] },
];

describe("mentionMatches — the import resolution seam", () => {
  it("finds aliases case-insensitively with word boundaries", () => {
    const hits = mentionMatches("MUM said hello to dad yesterday", PEOPLE);
    expect(hits.map((h) => h.person.id)).toEqual(["p-mum", "p-dad"]);
    expect(hits[0].text).toBe("MUM");
  });

  it("does not match partial words", () => {
    expect(mentionMatches("mumbling in the morning", PEOPLE)).toHaveLength(0);
    expect(mentionMatches("mummy is here", PEOPLE).map((h) => h.person.id)).toEqual(["p-mum"]);
  });

  it("matches a canonical name that ends in punctuation (2026-08-03 review)", () => {
    // \b can never match after ")" — the canonical-name-always-matches
    // invariant broke for names like "Marta (Ida)"
    const punctuated = [{ id: "p-marta", name: "Marta (Ida)", aliases: ["Ida"] }];
    expect(mentionMatches("Marta (Ida) wrote this", punctuated).map((h) => h.person.id)).toEqual(["p-marta"]);
    expect(mentionMatches("Marta (Ida) wrote this", punctuated)[0].text).toBe("Marta (Ida)");
    expect(mentionMatches("visit Marta (Ida)", punctuated).map((h) => h.person.id)).toEqual(["p-marta"]);
  });

  it("prefers the longer alias at the same start", () => {
    // "Mummy" starts with "Mum" — the longer alias must win
    const hits = mentionMatches("Mummy is here", PEOPLE);
    expect(hits).toHaveLength(1);
    expect(hits[0].text).toBe("Mummy");
  });

  it("links every distinct mention in order", () => {
    const hits = mentionMatches("Mum and Dad and Mum", PEOPLE);
    expect(hits.map((h) => h.person.id)).toEqual(["p-mum", "p-dad", "p-mum"]);
  });

  it("matches the canonical name even when it is not in aliases", () => {
    const hits = mentionMatches("Nora Hale is here", PEOPLE);
    expect(hits.map((h) => h.person.id)).toEqual(["p-mum"]);
  });

  it("carries the full person record, not the flattened entity (import seam)", () => {
    const [hit] = mentionMatches("Mum is here", PEOPLE);
    expect(hit.person.id).toBe("p-mum");
    expect(hit.person.name).toBe("Nora Hale");
  });
});

describe("linkMentions — reading experience", () => {
  it("builds anchors to cast pages around plain text", () => {
    const nodes = linkMentions("Mum wrote from Sundown", PEOPLE);
    const text = nodes.map((n) => n.textContent).join("");
    expect(text).toBe("Mum wrote from Sundown");
    const anchor = nodes.find((n) => n instanceof HTMLAnchorElement);
    expect(anchor.href).toContain("#/person/p-mum");
    expect(anchor.className).toBe("mention");
  });

  it("never uses innerHTML — text stays text", () => {
    const nodes = linkMentions("Mum <script>alert(1)</script>", PEOPLE);
    const anchor = nodes.find((n) => n instanceof HTMLAnchorElement);
    expect(anchor.textContent).toBe("Mum");
    expect(nodes.some((n) => n.textContent.includes("<script>"))).toBe(true);
  });
});

describe("linkMentions — place mentions (TECH-SPEC §16.4)", () => {
  const PLACES = [
    { id: "pl-westbrook", name: "31 Pinewood Court, Westbrook", aliases: ["Pinewood Court", "Westbrook"] },
    { id: "pl-marlock", name: "Marlock", aliases: [] },
  ];

  it("links place mentions to place pages alongside people", () => {
    const nodes = linkMentions("Mum wrote from Marlock", PEOPLE, PLACES);
    const anchors = nodes.filter((n) => n instanceof HTMLAnchorElement);
    expect(anchors.map((a) => a.href)).toEqual([
      expect.stringContaining("#/person/p-mum"),
      expect.stringContaining("#/place/pl-marlock"),
    ]);
    expect(anchors[1].className).toBe("mention place");
  });

  it("prefers the longest alias across people and places", () => {
    const nodes = linkMentions("from 31 Pinewood Court, Westbrook", PEOPLE, PLACES);
    const anchors = nodes.filter((n) => n instanceof HTMLAnchorElement);
    expect(anchors).toHaveLength(1); // the full address wins over "Pinewood Court" and "Westbrook"
    expect(anchors[0].textContent).toBe("31 Pinewood Court, Westbrook");
    expect(anchors[0].href).toContain("#/place/pl-westbrook");
  });

  it("leaves mentions without a record as plain text (F7)", () => {
    const nodes = linkMentions("She fled Tornia, exhausted", PEOPLE, PLACES);
    expect(nodes.filter((n) => n instanceof HTMLAnchorElement)).toHaveLength(0);
  });

  it('matches places case-sensitively — "a turkey" is dinner, "Tornia" is a place (§16.9)', () => {
    const WORLD = [{ id: "pl-tornia", name: "Tornia", aliases: [] }];
    expect(
      linkMentions("She cooked a turkey for Christmas", [], WORLD).filter((n) => n instanceof HTMLAnchorElement),
    ).toHaveLength(0);
    const nodes = linkMentions("They lived in Tornia", [], WORLD);
    const anchor = nodes.find((n) => n instanceof HTMLAnchorElement);
    expect(anchor?.href).toContain("#/place/pl-tornia");
    expect(anchor?.textContent).toBe("Tornia");
  });
});
