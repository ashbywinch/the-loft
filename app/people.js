/**
 * People and places identity — alias resolution. This is the import-process
 * seam: "Mum said…" resolves to a person record via aliases, "Marlock" to a
 * place record — so entities are first-class citizens, never passing mentions
 * (PRD §4, §6). One alias source, two consumers: reader links and the import
 * queue's proposals (TECH-SPEC §16.4).
 */

function escapeRe(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Flat entity list from people + places: {id, aliases, href, cls, ci}. */
function entityList(people, places) {
  return [
    // the canonical name always matches; aliases are the OTHER attested forms
    // ("mamie", "BF", "Alex") — never agent-invented terms
    ...(people ?? []).map((p) => ({
      id: p.id,
      aliases: [...new Set([p.name, ...(p.aliases ?? [])])],
      href: `#/person/${p.id}`,
      cls: "person",
      ci: true,
    })),
    // places match case-sensitively: "a turkey" (dinner) must not link to
    // Tornia the place (the actuality rule, TECH-SPEC §16.9)
    ...(places ?? []).map((p) => ({
      id: p.id,
      aliases: [...new Set([p.name, ...(p.aliases ?? [])])], // dedupe: name may repeat an alias
      href: `#/place/${p.id}`,
      cls: "place",
      ci: false,
    })),
  ];
}

/** Core matcher: sorted, non-overlapping, longest-first over any entities. */
function matchEntities(text, entities) {
  const matches = [];
  for (const entity of entities) {
    for (const alias of entity.aliases) {
      if (!alias) continue;
      // lookarounds, not \b: a canonical name ending in punctuation like
      // "Marta (Voss)" can never match with \b (no boundary after ")")
      // — the canonical-name-always-matches invariant (review, 2026-08-03)
      const re = new RegExp(`(?<![\\w])(${escapeRe(alias)})(?![\\w])`, entity.ci ? "gi" : "g");
      for (const m of text.matchAll(re)) {
        matches.push({ start: m.index, end: m.index + m[0].length, entity, text: m[0] });
      }
    }
  }
  matches.sort((a, b) => a.start - b.start || b.end - a.end);
  const chosen = [];
  let lastEnd = -1;
  for (const m of matches) {
    if (m.start < lastEnd) continue; // overlap — the longer alias won at this start
    chosen.push(m);
    lastEnd = m.end;
  }
  return chosen;
}

/** Find alias mentions of any person in text (import seam — person refs). */
export function mentionMatches(text, people) {
  const byId = new Map((people ?? []).map((p) => [p.id, p]));
  return matchEntities(text, entityList(people)).map((m) => ({ ...m, person: byId.get(m.entity.id) ?? m.entity }));
}

/** Render text with person and place mentions as links. */
export function linkMentions(text, people, places) {
  const nodes = [];
  let pos = 0;
  for (const m of matchEntities(text, entityList(people, places))) {
    if (m.start > pos) nodes.push(document.createTextNode(text.slice(pos, m.start)));
    const a = document.createElement("a");
    a.className = m.entity.cls === "place" ? "mention place" : "mention";
    a.href = m.entity.href;
    a.textContent = m.text;
    nodes.push(a);
    pos = m.end;
  }
  if (pos < text.length) nodes.push(document.createTextNode(text.slice(pos)));
  return nodes;
}
