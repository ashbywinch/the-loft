/**
 * Entity connections — the everything-to-everything graph, aggregated so it
 * scales: counts-first chips on entity pages, enumeration on the timeline.
 */

import { yearOf } from "./date.js";

function bump(map, id) {
  map.set(id, (map.get(id) ?? 0) + 1);
}

/** Count how often each entity type appears across the given items. */
/** Is this person involved in the item — as a subject (people[]) or as its teller? */
export function itemInvolves(item, personId) {
  return item.told_by === personId || item.people?.some((p) => p.id === personId);
}

/** Is this person AT this place in this item? An explicit per-place `people`
 *  list is authoritative (it may name someone outside the item's people[]);
 *  without one, everyone in the item's people[] is taken to be there. The
 *  'in' rule: a story's teller gains nothing from telling it — a teller
 *  outside the item's people[] and outside any per-place list never gets its
 *  places; a teller who IS a subject of the story (in people[]) is at its
 *  places like anyone else ("we sailed", 2026-08-03). The single attribution
 *  rule shared by the map, the person page and the chips. */
export function personAtPlace(personId, place) {
  // Presence must be attested per place — co-mention in an item is not being
  // there: the 2001 email mentions 8 places and 91 people, and nobody was at
  // all of them (2026-08-05). The explicit per-place people list is the only
  // seam; a place ref without one links nobody.
  return place.people?.includes(personId) ?? false;
}

/** The clarification fragments that attest a target — a fragment names its
 *  target in people or items refs, and it renders only there (2026-08-06). */
export function clarificationsFor(items, targetId) {
  return items.filter(
    (it) => it.clarification && (it.people?.some((p) => p.id === targetId) || it.items?.some((x) => x.id === targetId)),
  );
}

/** The reflections that mention a target — a reflection names who or where
 *  it is about in people or places refs, and it renders only there: it has
 *  no events' date, only the telling day (2026-08-06). */
export function reflectionsFor(items, targetId) {
  return items.filter(
    (it) => it.reflection && (it.people?.some((p) => p.id === targetId) || it.places?.some((p) => p.id === targetId)),
  );
}

/** The evidence records that attest a target — a found record (a web
 *  capture, a directory page) renders on the pages it attests, never on
 *  the timeline (2026-08-06). */
export function evidenceFor(items, targetId) {
  return items.filter(
    (it) => it.evidence && (it.people?.some((p) => p.id === targetId) || it.places?.some((p) => p.id === targetId) || it.items?.some((x) => x.id === targetId)),
  );
}

/** The date an item is placed at for an entity (person, place, object, org):
 *  the ref's attested involvement date — a guest book's signature, a
 *  logbook's boat entry — else the derived floor: an involvement can't
 *  predate the item, nor (for a person) their birth, so a birth-linked
 *  record sits at the person's entry (the family record at 1945 on Nora's
 *  page, never 1868). Calculated floors, attested dates override
 *  (2026-08-06). */
export function refDateFor(item, kind, entity) {
  const ref = (item[kind] ?? []).find((r) => r.id === entity?.id);
  if (ref?.date?.date) return ref.date.date;
  if (kind === "people" && entity?.dob?.date && entity.dob.date > item.date) return entity.dob.date;
  return item.date;
}

/** The date an item is placed at for a person — see refDateFor. */
export function itemDateFor(item, person) {
  return refDateFor(item, "people", person);
}

/** The back link: every item that references the target in its items refs —
 *  all links are bidirectional (2026-08-06): the boat story names Sunlight,
 *  and Sunlight's page shows "Referenced by: the boat story". */
export function referencedBy(items, itemId) {
  return items.filter((it) => (it.items ?? []).some((r) => r.id === itemId));
}

/** The non-story items of a set — stories render once, in the Memories
 *  block beside the list; an artifact list never re-shows them
 *  (2026-08-06, the render-once rule). */
export function artifacts(items) {
  return items.filter((it) => it.type !== "story");
}

/** Count how often each entity type appears across the given items.
 *  With personId, a place counts only when the person is AT it (personAtPlace). */
export function aggregate(items, personId) {
  const out = { people: new Map(), places: new Map(), themes: new Map() };
  for (const item of items) {
    for (const link of item.people ?? []) bump(out.people, link.id);
    for (const link of item.places ?? []) {
      if (personId && !personAtPlace(personId, link)) continue;
      bump(out.places, link.id);
    }
    for (const link of item.themes ?? []) bump(out.themes, link.id);
  }
  return out;
}

/** Map entries sorted by count desc, capped — never a wall of cards. */
export function sortedCounts(map, limit = 12) {
  return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit);
}

/** Items grouped into decade bands, most recent first. */
export function decadeBands(items) {
  const bands = new Map();
  for (const item of items) {
    const year = yearOf(item);
    if (!Number.isFinite(year)) continue; // malformed date — never a NaN decade band
    const decade = Math.floor(year / 10) * 10;
    if (!bands.has(decade)) bands.set(decade, []);
    bands.get(decade).push(item);
  }
  return [...bands.entries()].sort((a, b) => b[0] - a[0]).map(([decade, its]) => ({ decade, items: its }));
}

/** Parse a map-window query (?from=&to=); absent, empty, or invalid -> no window. */
export function windowFromQuery(query) {
  const fromRaw = query.get("from");
  const toRaw = query.get("to");
  if (fromRaw === null || toRaw === null || fromRaw.trim() === "" || toRaw.trim() === "") {
    return { inWindow: false, from: 0, to: 0 };
  }
  const from = Number(fromRaw);
  const to = Number(toRaw);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return { inWindow: false, from: 0, to: 0 };
  return { inWindow: true, from, to };
}
