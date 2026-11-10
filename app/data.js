/**
 * Data access — loads the published projection (app/data/*.json) once.
 * The archive itself lives elsewhere (TECH-SPEC §3–5); this is the projection.
 */

let state = null;

async function fetchJson(url) {
  // revalidate every load — the projection regenerates, so a cached copy
  // goes stale between loads
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) {
    throw new Error(`loadData: ${url} -> ${res.status}`);
  }
  return res.json();
}

export async function loadData() {
  if (state) return state;
  // The file-based fallback (a static host with no API) reads every file,
  // transcriptions included; the server boot uses `loadBootstrap` instead.
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

/** The app's one boot read: identity + projection in one request. */
export async function loadBootstrap() {
  const res = await fetch("/api/bootstrap", { headers: { Accept: "application/json" } });
  if (res.status === 404 || res.status === 410) return { noApi: true };
  if (res.status === 401) return { signedIn: false };
  if (!res.ok) throw new Error(`bootstrap -> ${res.status}`);
  const payload = await res.json();
  const items = payload.index?.items ?? [];
  state = {
    items,
    people: payload.people?.people ?? [],
    places: payload.places?.places ?? [],
    themes: payload.themes?.themes ?? [],
    relationships: payload.people?.relationships ?? [],
    imports: payload.imports?.imports ?? [],
    transcripts: {},
    byId: new Map(items.map((item) => [item.id, item])),
    me: payload.me?.authenticated ? payload.me : null,
  };
  return { signedIn: Boolean(payload.me?.authenticated), state };
}

/** The letter texts — one copy, fetched only by the Item/Search/Identify
 *  routes. The home, timeline and cast never pay for it. */
export async function loadTranscripts() {
  return fetchJson("data/transcripts.json");
}

export function assetUrl(itemId, file) {
  return `data/assets/${itemId}/${file}`;
}

export function typeLabel(type) {
  // story = testimonies and interview answers — a first-class artifact type
  // (PRD §19.5); it displays as a Memory so it never reads as a scanned
  // document. The DATA type stays "story".
  return { letter: "Letter", photo: "Photo", object: "Object", document: "Document", story: "Memory" }[type] ?? type;
}

/** A draft is for the person who claimed it — never an archival reader:
 *  the owner is the logged-in person once logins exist;
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
 *  attests. */
export function published(items) {
  return catalogued(items).filter((item) => !item.clarification && !item.reflection && !item.evidence);
}

export function drafts(items) {
  return items.filter((it) => it.status === "draft");
}

/** The import's unconfirmed people — a pending review, never family until
 *  confirmed (user: proposed people are an unfinished import). */
export function proposedPeople(state) {
  return (state.people ?? []).filter((p) => p.status === "proposed");
}

/** The unfinished document import sessions — the front page shows these,
 *  never the pending people list itself (user). */
export function pendingImports(state) {
  return (state.imports ?? []).filter((s) => s.status === "pending");
}

/** The portal's rows item: how many pages of the batches wait on the row
 *  check (`/api/sync/batches` carries the page names, not a count). */
export function pagesToCheck(batches) {
  return (batches ?? []).reduce(
    (count, batch) => count + (batch.status === "confirmed" ? 0 : (batch.pages_pending ?? []).length),
    0,
  );
}

/** The portal's transcripts item: the documents still awaiting the review
 *  gate — a boundary not yet confirmed, in a batch not yet confirmed. */
export function documentsToReview(batches) {
  // the transcription review is the stage AFTER the row check: a batch's
  // `documents_ready` lists the documents whose pages are all checked, and
  // only those are reviewable words (docs/PLAN/row-correction-rule.md; a
  // strip-era batch has none — its pages were never read as rows)
  return (batches ?? [])
    .filter((batch) => batch.status !== "confirmed")
    .reduce((count, batch) => count + (batch.documents_ready ?? []).length, 0);
}

/** The documents whose people and places still wait on the family (stage 8):
 *  a document with a transcription that the identification pass has not read,
 *  or that has a mention still proposed. The review hub lists them; the
 *  front page only counts them behind its single review door. */
export function documentsToIdentify(state) {
  return (state.items ?? []).filter((item) => {
    const hasText = item.has_transcription ?? Boolean((item.transcription || "").trim());
    if (item.type !== "document" || !hasText) return false;
    const refs = [...(item.people ?? []), ...(item.places ?? [])];
    return !item.identified || refs.some((ref) => ref.status === "proposed");
  });
}

/** The signed-in identity — state.me comes from /api/auth/me at boot (the
 *  capture server mints it from a verified Google account; the static host
 *  has no API, so me is null and the archive stays browsable). The narrator
 *  IS this identity — the localStorage name claim is gone (user: implement
 *  google auth, get rid of the hackery). */
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
 *  the verified session — the client never claims a name. */
export function isMine(draft, state) {
  const mine = me(state);
  if (!mine?.person) return false;
  return draft.told_by === mine.person;
}

/** Whether an asset file is a page image the app can render. A PDF is a
 *  source document, not an image — the viewer links it instead. */
export function isImageAsset(file) {
  return /\.(jpe?g|png|webp|gif|svg)$/i.test(String(file ?? ""));
}
