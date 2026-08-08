/**
 * Data access — loads the published projection (app/data/*.json) once.
 * The archive itself lives elsewhere (TECH-SPEC §3–5); this is the projection.
 */

let state = null;

async function fetchJson(url) {
  // revalidate every load — the projection regenerates and the curator kept
  // seeing stale cached data (2026-08-03)
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) {
    throw new Error(`loadData: ${url} -> ${res.status}`);
  }
  return res.json();
}

export async function loadData() {
  if (state) return state;
  const [index, people, places, themes, transcripts, imports] = await Promise.all([
    fetchJson("data/index.json"),
    fetchJson("data/people.json"),
    fetchJson("data/places.json"),
    fetchJson("data/themes.json"),
    fetchJson("data/transcripts.json"),
    fetchJson("data/imports.json"),
  ]);
  state = {
    items: index.items,
    people: people.people,
    places: places.places,
    themes: themes.themes,
    relationships: people.relationships ?? [],
    imports: imports.imports ?? [],
    transcripts,
    byId: new Map(index.items.map((item) => [item.id, item])),
  };
  return state;
}

export function assetUrl(itemId, file) {
  return `data/assets/${itemId}/${file}`;
}

export function typeLabel(type) {
  // story = testimonies and interview answers — a first-class artifact type
  // (PRD §19.5); it displays as a Memory so it never reads as a scanned
  // document (user, 2026-08-03). The DATA type stays "story".
  return { letter: "Letter", photo: "Photo", object: "Object", document: "Document", story: "Memory" }[type] ?? type;
}

/** A draft is for the person who claimed it — never an archival reader
 *  (user, 2026-08-03): the owner is the logged-in person once logins exist;
 *  until then, the person who said they were writing it. The archival views
 *  read through ``catalogued()``; only the drafts surface reads ``drafts()``.
 *  This is the one seam — a view that filters statuses itself is a finding. */
export function catalogued(items) {
  return items.filter((item) => item.status !== "draft");
}

/** What a reader meets on the discovery surfaces — catalogued minus
 *  clarification fragments, reflections and evidence records. None of them
 *  are family happenings: a fragment attests identity, a reflection is
 *  perspective, an evidence record (a web capture, a directory page) is
 *  found material ABOUT the family — each renders only on the pages it
 *  attests (2026-08-06). */
export function published(items) {
  return catalogued(items).filter((item) => !item.clarification && !item.reflection && !item.evidence);
}

export function drafts(items) {
  return items.filter((it) => it.status === "draft");
}

/** The import's unconfirmed people — a pending review, never family until
 *  confirmed (2026-08-07, user: proposed people are an unfinished import). */
export function proposedPeople(state) {
  return (state.people ?? []).filter((p) => p.status === "proposed");
}

/** The unfinished document import sessions — the front page shows these,
 *  never the pending people list itself (user, 2026-08-07). */
export function pendingImports(state) {
  return (state.imports ?? []).filter((s) => s.status === "pending");
}

/** The signed-in identity — state.me comes from /api/auth/me at boot (the
 *  capture server mints it from a verified Google account; the static host
 *  has no API, so me is null and the archive stays browsable). The narrator
 *  IS this identity — the localStorage name claim is gone (2026-08-06, user:
 *  implement google auth, get rid of the hackery). */
export function me(state) {
  return state.me ?? null;
}

/** The signed-in narrator's person record, or null. */
export function mePerson(state) {
  const mine = me(state);
  if (!mine?.person) return null;
  return state.people.find((p) => p.id === mine.person) ?? null;
}

/** Is this draft the signed-in narrator's? The server mints told_by from
 *  the verified session — the client never claims a name (2026-08-06). */
export function isMine(draft, state) {
  const mine = me(state);
  if (!mine?.person) return false;
  return draft.told_by === mine.person;
}
