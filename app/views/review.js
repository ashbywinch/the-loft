/**
 * The transcription-review surface (TECH-SPEC §16.16 + the locked wireframe,
 * 2026-08-15): the reviewer checks the machine's drafts against the pages
 * before they are archived. The page image (a plain <img> in a scaled
 * layer — the OpenSeadragon viewer was replaced 2026-08-16, see below)
 * shows the detector's line boxes; the transcription pane shows the VLM's
 * verbatim lines with the low-confidence words flagged (the transcription
 * model's own self-report, tools/selfreport.py — a word the model is
 * unsure of, or that reads oddly in context; the ~~struck~~ words always
 * flag); a flagged word enters per-line inline editing anchored to the
 * image (the line's box highlights and the image pans to it). The only gate is confirmation — Confirm & Next records the
 * corrected document through the sync seam (POST /api/sync/confirmations)
 * with a localStorage outbox as the catch-up when the backend is
 * unreachable (TECH-SPEC §16.15: nothing confirmed is ever lost to a
 * failed push).
 *
 * Phone portrait shows a "turn your phone sideways" prompt; phone
 * landscape splits horizontally (letter full-width on top, words below);
 * tablet/desktop split vertically (letter left, words right) — the locked
 * design (VR8, user 2026-08-15).
 */

import { el } from "../ui.js";
import { navigate } from "../router.js";
import { gateScreen } from "../gate.js";
import { drafts as draftItems, isMine, me, pendingImports, proposedPeople } from "../data.js";

const OUTBOX_KEY = "loft-review-outbox";
const EDITS_KEY = "loft-review-edits";

// -- the reviewer's edits persist (VR9: bounded and resumable) ----------------
// The confirmed write happens only on the last page, but the fixes must
// survive an accidental exit mid-document — per (batch, doc), restored on
// reopen, cleared once the confirmation lands (walk finding 3, 2026-08-15).

export function loadEdits(batchId, docIndex) {
  try {
    const all = JSON.parse(localStorage.getItem(EDITS_KEY) || "{}");
    return all?.[batchId]?.[String(docIndex)] || {};
  } catch {
    return {};
  }
}

/** Reconcile edits against a layout: when the layout changes (new pipeline
 *  run, re-aligned lines), the edits' line indices can become stale. For
 *  each edit, if the text at its index no longer matches, try to find the
 *  edit's text elsewhere in the layout and re-map the index. Edits that
 *  can't be matched are dropped — the reviewer re-checks those lines.
 *  Returns a new edits dict with the re-mapped indices. */
export function reconcileEdits(edits, layout) {
  // An edit (a corrected text, or a "mark fine" of the verbatim text)
  // stays valid ONLY while the line it belongs to still carries the same
  // text. When the pipeline rebuilds a page and the transcription changes,
  // the old edits must ORPHAN — the reviewer re-verifies the changed lines
  // (user, 2026-08-22: "keeping the state if the new boxes or guessed
  // transcriptions are different would also be bad"). The match is EXACT —
  // a fuzzy re-map (edit distance <=3) attached old corrections to the
  // wrong lines after a rebuild, mixing the user's verified text with the
  // raw transcription.
  if (!layout || !layout.lines) return edits;
  const lines = layout.lines;
  const result = {};
  for (const [idxStr, text] of Object.entries(edits)) {
    const idx = Number(idxStr);
    const lineAtIdx = lines.find((l) => l.index === idx);
    if (lineAtIdx && lineAtIdx.text === text) {
      result[idx] = text; // the line's text is unchanged — the edit holds
      continue;
    }
    // The line at this index changed (or moved). Keep the edit only when
    // its exact text exists elsewhere in the layout.
    const matched = lines.find((l) => l.text === text);
    if (matched && !result[matched.index]) {
      result[matched.index] = text;
      continue;
    }
    // The transcription changed under this edit — orphan it.
  }
  return result;
}

export function saveEdits(batchId, docIndex, edits) {
  try {
    const all = JSON.parse(localStorage.getItem(EDITS_KEY) || "{}");
    all[batchId] = all[batchId] || {};
    all[batchId][String(docIndex)] = edits;
    localStorage.setItem(EDITS_KEY, JSON.stringify(all));
  } catch {
    // storage unavailable — the session still holds the edits
  }
}

export function clearEdits(batchId, docIndex) {
  try {
    const all = JSON.parse(localStorage.getItem(EDITS_KEY) || "{}");
    delete all?.[batchId]?.[String(docIndex)];
    localStorage.setItem(EDITS_KEY, JSON.stringify(all));
  } catch {
    // nothing to clear
  }
}
/** Save the current page\'s review state (scroll, view, selected line) to
 * localStorage so the reviewer never loses their place (VR9, VR17).
 * Keyed by batch + page index; expects the doc index to validate. */
export function saveResumePosition(batchId, docIndex, pageId, selLine, view, scrollTop, readRotation) {
  try {
    const key = `rv-res-${batchId}-${pageId}`;
    const data = JSON.stringify({ docIndex, selLine, view, scrollTop, readRotation, ts: Date.now() });
    localStorage.setItem(key, data);
  } catch { /* quota exceeded */ }
}

export function loadResumePosition(batchId, pageId) {
  try {
    const key = `rv-res-${batchId}-${pageId}`;
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch { return null; }
}

export function clearResumePosition(batchId, pageId) {
  try {
    localStorage.removeItem(`rv-res-${batchId}-${pageId}`);
  } catch { /* ignore */ }
}

/** Save the current session page's resume position before navigation. */
function saveCurrentResumePosition(session) {
  const { batch, docIndex, pageIndex, selLine, view, readRotation } = session;
  const doc = batch.documents[docIndex];
  const pageId = doc?.pages?.[pageIndex];
  if (pageId !== undefined && session.txBody) {
    saveResumePosition(batch.batchId, docIndex, pageId, selLine, view, session.txBody.scrollTop ?? 0, readRotation);
  }
}

/** The full bounding box of all lines in the layout, or null if there
 * are no line boxes. The margin is the line-0 top: the band anchor\'s
 * half-line margin. */
export function initialViewRect(layout) {
  // The initial view zooms to the FIRST boxed line — the review starts at
  // the letter's first line, readable (2026-08-22, user: "the whole letter
  // is zoomed right out and stuck in the corner"). Same padding as the
  // zoom-to-line click, so the first visit and the first click agree. The
  // fit-to-content (the whole letter) stays available via the fit button.
  const first = (layout?.lines || []).find((l) => l.box);
  if (!first) return null;
  const [x0, y0, x1, y1] = first.box;
  const pad = Math.max(x1 - x0, y1 - y0) * 0.04;
  return { x: x0 - pad, y: y0 - pad, width: x1 - x0 + 2 * pad, height: y1 - y0 + 2 * pad };
}

function contentBounds(layout) {
  const lines = (layout?.lines || []).filter((l) => l.box);
  if (!lines.length) return null;
  const allX = lines.flatMap((l) => [l.box[0], l.box[2]]);
  const allY = lines.flatMap((l) => [l.box[1], l.box[3]]);
  const r = Math.max(allX[1] - allX[0], allY[1] - allY[0]) * 0.05;
  return {
    x: Math.min(...allX) - r,
    y: Math.min(...allY) - r,
    width: Math.max(...allX) - Math.min(...allX) + 2 * r,
    height: Math.max(...allY) - Math.min(...allY) + 2 * r,
  };
}

/** Reject (bin) persistence: a simple localStorage marker so the batch
 *  list filters rejected documents across page loads. The bin is
 *  recoverable (AC30): clearRejection reinstates the document. */
export function saveRejection(batchId, docIndex) {
  try {
    const key = `rv-rej-${batchId}-${docIndex}`;
    localStorage.setItem(key, "1");
  } catch { /* ignore */ }
}

export function loadRejections(batchId) {
  try {
    const prefix = `rv-rej-${batchId}-`;
    const set = new Set();
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix)) set.add(k.slice(prefix.length));
    }
    return set;
  } catch { return new Set(); }
}

export function clearRejection(batchId, docIndex) {
  try {
    localStorage.removeItem(`rv-rej-${batchId}-${docIndex}`);
  } catch { /* ignore */ }
}

// -- pure helpers (exported for tests) ----------------------------------------

/** The document's lines still to check: lines carrying a flagged (conf 0)
 *  word that the reviewer hasn't verified by editing. The review unit is
 *  the LINE — fixing a line clears all its flags (the walk: one edit
 *  dropped six red words) — so the count names the work honestly
 *  (2026-08-15: "254 words" overstated it; the data showed the detector's
 *  rec model is confidently wrong on cursive, and most word-level flags
 *  are that second reader's noise). Pages without a layout have nothing to
 *  check. */
export function flaggedCount(documents, docIndex, edits) {
  return flaggedPositions(documents, docIndex, edits).length;
}

/** The flagged lines of a document in reading order — page order, then
 *  line order; a line counts once however many of its words are flagged. */
export function flaggedPositions(documents, docIndex, edits) {
  const doc = documents[docIndex];
  const positions = [];
  for (const page of doc.pages) {
    const layout = doc.layouts?.[page];
    if (!layout) continue;
    const pageEdits = edits[page] || {};
    for (const line of layout.lines) {
      if (line.index in pageEdits) continue;
      if (line.words.some((w) => w.conf === 0)) positions.push({ page, line: line.index });
    }
  }
  return positions;
}

/** The remaining flagged lines per page — the page chips' flag dots
 *  (2026-08-16: the dots make a cross-page jump visible before any
 *  press; the map replaces the hint words). */
export function flaggedByPage(documents, docIndex, edits) {
  const byPage = {};
  for (const { page } of flaggedPositions(documents, docIndex, edits)) {
    byPage[page] = (byPage[page] || 0) + 1;
  }
  return byPage;
}

/** The corrected text of one page: the layout's verbatim lines with the
 *  reviewer's edits applied; a page with no layout is its raw guess. */
export function correctedPageText(doc, page, edits) {
  const layout = doc.layouts?.[page];
  if (layout) {
    const pageEdits = edits[page] || {};
    return layout.lines.map((l) => pageEdits[l.index] ?? l.text).join("\n");
  }
  return doc.texts?.[page] || "";
}

/** The corrected document text — pages joined with "\n", the same shape
 *  the CLI review gate confirms (tools/pipeline.py review()). */
export function correctedDocumentText(doc, edits) {
  return doc.pages.map((p) => correctedPageText(doc, p, edits)).join("\n");
}

// -- the outbox (the JS mirror of tools/sync.py Outbox: nothing confirmed
//    is lost to a failed push) ------------------------------------------------

export function outboxPending() {
  try {
    const items = JSON.parse(localStorage.getItem(OUTBOX_KEY) || "[]");
    return Array.isArray(items) ? items : [];
  } catch {
    return [];
  }
}

export function outboxAdd(payload) {
  const items = outboxPending();
  items.push(payload);
  localStorage.setItem(OUTBOX_KEY, JSON.stringify(items));
}

export function outboxDrop(payload) {
  const key = JSON.stringify(payload);
  localStorage.setItem(
    OUTBOX_KEY,
    JSON.stringify(outboxPending().filter((p) => JSON.stringify(p) !== key)),
  );
}

async function postConfirmation(payload) {
  const res = await fetch("/api/sync/confirmations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`confirmation rejected (${res.status})`);
}

/** Push a confirmation; on failure it stays in the outbox. The outbox is
 *  retried on every subsequent confirm and on the batch screen. Returns
 *  whether the backend recorded it. */
async function confirmDocument(payload) {
  try {
    await postConfirmation(payload);
  } catch (error) {
    console.warn("review: push failed — kept in the outbox", error);
    outboxAdd(payload);
    return false;
  }
  await retryOutbox();
  return true;
}

/** Retry the outbox's pending confirmations (the laptop was off); drop
 *  each item once the backend records it. */
async function retryOutbox() {
  for (const item of outboxPending()) {
    try {
      await postConfirmation(item);
      outboxDrop(item);
    } catch {
      return; // still unreachable — leave the rest
    }
  }
}

// -- the view -----------------------------------------------------------------

export function render(main, ctx, state) {
  // The pre-VR10 rotation outbox (`loft-review-rotates`) was an array of
  // auto-delivered intents that could reorient a page the reviewer never
  // touched. It is gone — the reviewer's orientation now lives as
  // { desired, acked } in `loft-review-orientations`, set only by ↻. Drop
  // any stale legacy entries so they can never re-deliver (2026-08-16).
  localStorage.removeItem("loft-review-rotates");
  if (ctx.arg) {
    // #/review/<batch>/<doc>/<page> — the surface's position lives in the
    // URL (user 2026-08-16: refreshing the browser must restore the page
    // you're on, not drop you back to the document list). rest is
    // [review, <batch>, <doc>, <page>] — the batch is also ctx.arg.
    const doc = Number(ctx.rest?.[2]);
    const page = Number(ctx.rest?.[3]);
    const initial = Number.isInteger(doc) && Number.isInteger(page) ? { doc, page } : null;
    renderBatch(main, ctx.arg, state, initial);
  } else {
    renderBatchList(main, state);
  }
}

/** The sign-in gate (the sync APIs are private) — same screen as the
 *  archive gate so the reviewer knows what to do. */
function signedOut(main) {
  main.replaceChildren(gateScreen());
}

/** An error screen is never a dead end (walk finding 2, 2026-08-16: the
 *  PhotoScan 400 left Elaine trapped with no navigation — a non-technical
 *  user cannot be expected to find the browser's back arrow). Every
 *  failure renders the top bar with a back arrow plus the message. */
function renderError(main, message, backTarget = "home") {
  const root = el("div", { class: "rv" }, [
    el("div", { class: "rv-topbar" }, [
      el("button", { class: "rv-back", onclick: () => navigate(backTarget) }, "← Home"),
      el("div", { class: "rv-topbar-titles" }, [el("div", { class: "rv-tt" }, "Review")]),
    ]),
    el("div", { class: "rv-note" }, message),
  ]);
  main.replaceChildren(root);
}

async function renderBatchList(main, state) {
  let batches;
  try {
    const res = await fetch("/api/sync/batches", { headers: { Accept: "application/json" } });
    if (res.status === 401) return signedOut(main);
    if (!res.ok) throw new Error(`batches (${res.status})`);
    batches = (await res.json()).batches;
  } catch (error) {
    renderError(main, `Could not load the batches (${error.message}).`);
    return;
  }
  // a batch with nothing left to review (all boundaries confirmed, or the
  // registry says so) does not belong on the review hub (user 2026-08-16);
  // the empty message appears only when there is genuinely no review work
  // anywhere — state is always the app state object, so `!state` never
  // fired and the hub rendered blank (bot review, 2026-08-16)
  const open = batches.filter(
    (b) => b.status !== "confirmed" && (b.boundaries ?? []).some((x) => x.status !== "confirmed"),
  );
  const hasWork =
    open.length > 0 ||
    (state &&
      (pendingImports(state).length > 0 || draftItems(state.items).length > 0));
  if (!hasWork) {
    renderError(main, "No review work waiting — everything is confirmed.");
    return;
  }
  main.append(
    el("div", { class: "rv-topbar" }, [
      el("button", { class: "rv-back", onclick: () => navigate("home") }, "← Home"),
      el("div", { class: "rv-topbar-titles" }, [
        el("div", { class: "rv-tt" }, "Review"),
      ]),
    ]),
  );

  if (open.length) {
    main.append(el("h2", { class: "rv-section-title" }, "Transcriptions — check the machine's reading of scanned pages"));
    const list = el("div", { class: "rv-list" });
    for (const batch of open) {
      const boundaries = batch.boundaries || [];
      const confirmed = boundaries.filter((b) => b.status === "confirmed").length;
      const pages = Object.keys(batch.pages || {}).length;
      const progress = boundaries.length
        ? `${confirmed} of ${boundaries.length} confirmed`
        : `${pages} pages`;
      const card = el(
        "button",
        { class: "rv-card", onclick: () => navigate(`review/${batch.batch_id}`) },
        [
          el("div", { class: "rv-card-main" }, [
            el("div", { class: "rv-card-title" }, batch.label || batch.batch_id),
            el("div", { class: "rv-card-sub" }, progress),
          ]),
          el(
            "span",
            { class: "rv-chip" },
            confirmed && confirmed === boundaries.length ? "Reviewed" : "Awaiting review",
          ),
        ],
      );
      list.append(card);
    }
    main.append(list);
  }

  // Import sessions — identity extraction from documents (the Judith doc etc.)
  if (state) {
    const pending = pendingImports(state);
    if (pending.length) {
      const count = proposedPeople(state).length;
      const note =
        count === 1
          ? "1 person from the import is waiting to be confirmed — the tree shows only confirmed family."
          : `${count} people from the import are waiting to be confirmed — the tree shows only confirmed family.`;
      main.append(el("h2", { class: "rv-section-title" }, "Import sessions — confirm who belongs in the family tree"));
      const list = el("div", { class: "rv-list" });
      pending.forEach((session) => {
        const card = el(
          "button",
          { class: "rv-card", onclick: () => navigate(`import/${session.id}`) },
          [
            el("div", { class: "rv-card-main" }, [
              el("div", { class: "rv-card-title" }, session.title || "Import session"),
              el("div", { class: "rv-card-sub" }, note),
            ]),
            el("span", { class: "rv-chip" }, "Awaiting review"),
          ],
        );
        list.append(card);
      });
      main.append(list);
    }
  }

  // Drafts — unfinished stories (user, 2026-08-16: "Drafts ARE review work")
  if (state) {
    const allDrafts = draftItems(state.items);
    const signedIn = me(state);
    const shown = signedIn ? allDrafts.filter((d) => isMine(d, state)) : allDrafts;
    if (shown.length) {
      const label = signedIn ? "Your unfinished stories" : "Unfinished stories";
      main.append(el("h2", { class: "rv-section-title" }, `${label} — pick up where you left off`));
      const list = el("div", { class: "rv-list" });
      shown.forEach((d) => {
        const title = d.title || d.text?.slice(0, 60) || "Untitled";
        const card = el(
          "button",
          { class: "rv-card", onclick: () => navigate(`/item/${d.id}`) },
          [
            el("div", { class: "rv-card-main" }, [
              el("div", { class: "rv-card-title" }, title),
              el("div", { class: "rv-card-sub" }, "Click to continue this story"),
            ]),
            el("span", { class: "rv-chip" }, "Draft"),
          ],
        );
        list.append(card);
      });
      main.append(list);
    }
  }
}

/** The batch's document cards — the wireframe's VIEW 1 with real data. */
async function renderBatch(main, batchId, state, initial = null) {
  let data;
  try {
    const res = await fetch(`/api/sync/batch/${encodeURIComponent(batchId)}/drafts`, {
      headers: { Accept: "application/json" },
    });
    if (res.status === 401) return signedOut(main);
    if (!res.ok) throw new Error(`drafts (${res.status})`);
    data = await res.json();
  } catch (error) {
    renderError(main, `Could not load the drafts (${error.message}).`);
    return;
  }
  await retryOutbox();
  // safely attempt any owed reorientations (the display never reads the
  // delivery state, so this cannot reorient a page the reviewer didn't
  // press — VR10 AC13); fire-and-forget: the batch list renders now
  void deliverOwed();
  const documents = data.documents || [];
  const confirmed = documents.filter((d) => d.status === "confirmed").length;
  const root = el("div", { class: "rv" }, [
    el("div", { class: "rv-topbar" }, [
      el("button", { class: "rv-back", onclick: () => navigate("review") }, "← Review"),
      el("div", { class: "rv-topbar-titles" }, [
        el("div", { class: "rv-tt" }, data.label || batchId),
        el("div", { class: "rv-ts" }, `${confirmed} of ${documents.length} in this batch confirmed`),
      ]),
    ]),
  ]);
  main.replaceChildren(root);
  if (!documents.length) {
    root.append(el("div", { class: "rv-note" }, "This batch has no text documents to review."));
    root.append(el("button", { class: "rv-btn", onclick: () => renderBatchList(root, state) }, "← Back to review"));
    return;
  }
  // a URL with the surface's position (a refresh) restores it directly
  if (initial) {
    const { doc, page } = initial;
    if (Number.isInteger(doc) && doc >= 0 && doc < documents.length) {
      const session = makeSession({ batchId, label: data.label, documents, processing: data.processing || {} }, doc);
      session.pageIndex = Math.min(Math.max(page, 0), documents[doc].pages.length - 1);
      renderSurface(root, session);
      return;
    }
  }
  // Confirmed and rejected documents are not listed — the review list is
  // the work still to do (user 2026-08-16: "if it WAS confirmed it
  // shouldn't be listed"). The original documents index is kept for the
  // confirmation payload (the CLI gate's 1-based boundaries order).
  // apply persisted rejections before filtering
  const rejectedSet = loadRejections(batchId);
  documents.forEach((d, i) => { if (rejectedSet.has(String(i))) d.status = "rejected"; });
  const awaiting = documents
    .map((doc, i) => ({ doc, i }))
    .filter(({ doc }) => doc.status !== "confirmed" && doc.status !== "rejected");
  if (!awaiting.length) {
    root.append(
      el("div", { class: "rv-note" }, `All ${documents.length} document${documents.length === 1 ? "" : "s"} in this batch ${documents.length === 1 ? "is" : "are"} confirmed.`),
    );
    return;
  }
  const list = el("div", { class: "rv-list" });
  awaiting.forEach(({ doc, i }, n) => {
    const chip = el("span", { class: "rv-chip" }, "Awaiting review");
    // the hint that makes a document identifiable: its greeting, or the
    // first line of its first page — never the technical page ids
    // (walk finding 6, 2026-08-15)
    const hint =
      doc.greeting ||
      (doc.pages[0] && doc.texts?.[doc.pages[0]]
        ? doc.texts[doc.pages[0]].split("\n").find((l) => l.trim())?.trim().slice(0, 48)
        : null);
    const card = el(
      "button",
      {
        class: "rv-card",
        onclick: () => openReview(root, { batchId, label: data.label, documents, processing: data.processing || {} }, i),
      },
      [
        el("div", { class: "rv-card-main" }, [
          el("div", { class: "rv-card-title" }, `Document ${n + 1} of ${awaiting.length}`),
          el("div", { class: "rv-card-sub" }, `${doc.pages.length} pages${hint ? ` · begins “${hint}”` : ""}`),
        ]),
        chip,
      ],
    );
    list.append(card);
  });
  root.append(list);
}

// -- the review surface -------------------------------------------------------

/** The surface's position lives in the URL (#/review/<batch>/<doc>/<page>)
 * so the browser refresh restores the page you're on (user 2026-08-16:
 * refreshing must never drop you back to a different page). replaceState
 * keeps the flips in-place (fast, selection preserved) while making the
 * position refreshable. */
function syncSurfaceUrl(session) {
  if (!session?.batch?.batchId) return;
  const target = `#/review/${session.batch.batchId}/${session.docIndex}/${session.pageIndex}`;
  if (location.hash !== target) history.replaceState(null, "", target);
}

function makeSession(batch, docIndex) {
  return {
    batch,
    docIndex,
    pageIndex: 0,
    edits: loadEdits(batch.batchId, docIndex), // page -> {lineIndex: correctedText} — resumable (VR9)
    selLine: null, // selected transcription line (or null)
    editing: null, // line index in edit mode (or null)
    from: null, // last-visited flag position
    root: null, // the rv DOM root (filled by renderSurface)
    txBody: null, // the transcription pane body
    imgBox: null, // the page-image pane (filled by openViewer)
    layer: null, // the transform-scaled layer: the <img> + the line boxes
    img: null, // the page <img>
    imgSize: null, // {w, h} — the image's natural size, once loaded
    view: null, // the visible rectangle in display px {x, y, width, height}
    overlays: [], // the line-box overlay elements
    contentTop: 0, // the writing's first line-box top (rot 0) — the band anchor
    resizer: null, // the pane resize observer (re-fit when it becomes visible)
    userMoved: false, // the reviewer has panned/zoomed — stop auto-fitting
    lastFitSize: null, // the pane size the initial view fitted against
    baseRotation: 0, // the backend's applied rotation for the current page
    rotation: 0, // the current page's view rotation (the reviewer's delta)
    syncLock: false, // the dual-pane link's feedback lock
    processingTimer: null, // the poll while the backend re-reads the page
  };
}

function openReview(main, batch, docIndex) {
  renderSurface(main, makeSession(batch, docIndex));
}

function docTitle(doc) {
  if (doc.greeting) return doc.greeting;
  if (doc.pages[0]) {
    const first = doc.texts?.[doc.pages[0]]?.split("\n").find((l) => l.trim())?.trim().slice(0, 48);
    if (first) return first;
  }
  return doc.pages[0] || "Document";
}

function renderSurface(main, session) {
  const { batch, docIndex } = session;
  const doc = batch.documents[docIndex];
  if (!doc) {
    renderError(main, "No more documents in this batch.");
    return;
  }
  const page = doc.pages[session.pageIndex];
  // The page's orientation: the backend's applied rotation (the layout's
  // "rotation") plus the reviewer's correction. A page CHANGE loads the
  // pending intent from the outbox (the reviewer's committed fix, restored
  // whether or not the sync has delivered it); a re-render of the SAME
  // page keeps the live value (the presses are uncommitted until the next
  // navigation — 2026-08-16: front and back end are different boxes; the
  // backend may be off).
  session.baseRotation = doc.layouts?.[page]?.rotation ?? 0;
  // a page being reworked on the backend must not be shown — land on the
  // next available page instead (user 2026-08-16: "it shouldn't have
  // shown me it at all once we'd established that it needed rework")
  if (isReworking(batch, page)) {
    // land on the next available page after this one — never backward
    // (a wrap would loop the confirm on a doc whose tail is all reworking)
    const next = nextAvailableAfter(doc, batch, session.pageIndex);
    if (next !== -1) {
      session.pageIndex = next;
      session.selLine = null;
      session.editing = null;
      renderSurface(main, session);
      return;
    }
    // the rest of the document is being reworked — show this page's
    // fixing note
  }
  if (session.lastPage !== page) {
    session.lastPage = page;
    // The display rotation = the reviewer's DESIRED orientation minus the
    // backend's applied rotation. The desired is an absolute quarter-turn
    // that only a ↻ press changes; a page never pressed shows the backend
    // orientation as-is (desired == base → delta 0). It is never derived
    // from a delivery queue, so nothing stale can reorient the view.
    const st =
      orientationState(batch.batchId, page) || { desired: baseQuarters(session.baseRotation), acked: baseQuarters(session.baseRotation) };
    session.desired = st.desired;
    session.acked = st.acked;
    session.rotation = deltaOfDesired(st.desired, session.baseRotation);
  }
  // the dots exclude the rework pages — their flags will change when the
  // backend re-reads them
  const positions = availablePositions(session);

  const root = el("div", { class: "rv" });
  // One bar for the whole chrome: back, the document's name, and BOTH
  // sequences as chips (2026-08-16: the count chip was the extraneous
  // piece — the same count is already on the Next-flagged badge and the
  // page dots; the document boundary and the cross-page jump are visible
  // before any press, so nothing needs explaining).
  const topbar = el("div", { class: "rv-topbar" }, [
    el("button", { class: "rv-back", onclick: async () => { saveCurrentResumePosition(session); acceptEdit(session); await queueRotation(session); navigate(`review/${batch.batchId}`); } }, `← ${batch.label || "Documents"}`),
    el("div", { class: "rv-topbar-titles" }, [
      el("div", { class: "rv-tt" }, docTitle(doc)),
    ]),
  ]);
  // the page chips' flag dots come from the AVAILABLE positions — a
  // rework page shows the fixing state instead (its flags will change)
  const flagsByPage = {};
  for (const { page: p } of positions) flagsByPage[p] = (flagsByPage[p] || 0) + 1;
  const docGroup = el("div", { class: "rv-navgroup" });
  batch.documents.forEach((d, i) => {
    const cls =
      "rv-navchip rv-navchip--doc" +
      (i === docIndex ? " rv-navchip--cur" : "") +
      (d.status === "confirmed" ? " rv-navchip--done" : "");
    docGroup.append(
      el(
        "button",
        {
          class: cls,
          onclick: async () => {
            acceptEdit(session);
            await queueRotation(session);
            saveCurrentResumePosition(session);
            openReview(root, batch, i);
          },
          title: d.greeting || `Document ${i + 1}`,
          "aria-label": `Document ${i + 1}${d.status === "confirmed" ? ", confirmed" : ""}`,
        },
        d.status === "confirmed" ? "✓" : String(i + 1),
      ),
    );
  });
  const pageGroup = el("div", { class: "rv-navgroup" });
  doc.pages.forEach((p, i) => {
    const remaining = flagsByPage[p] || 0;
    const reworking = isReworking(batch, p);
    const cls =
      "rv-navchip" +
      (i === session.pageIndex ? " rv-navchip--cur" : "") +
      (reworking ? " rv-navchip--fixing" : remaining ? " rv-navchip--flag" : "");
    pageGroup.append(
      el(
        "button",
        {
          class: cls,
          onclick: async () => {
            acceptEdit(session);
            await queueRotation(session);
            saveCurrentResumePosition(session);
            session.pageIndex = i;
            session.selLine = null;
            session.editing = null;
            renderSurface(session.root, session);
          },
          title: `Page ${i + 1}${remaining ? ` — ${remaining} ${remaining === 1 ? "line" : "lines"} to check` : ""}`,
          "aria-label": `Page ${i + 1}${remaining ? `, ${remaining} lines to check` : ""}`,
        },
        String(i + 1),
      ),
    );
  });
  topbar.append(docGroup, el("div", { class: "rv-navsep" }), pageGroup);

  const rotate = el("div", { class: "rv-rotate" }, [
    el("div", { class: "rv-rotate-icon" }, "↻"),
    el("h2", {}, "Turn your phone sideways"),
    el("p", {}, "The review screen works in landscape — the letter image needs the width."),
  ]);

  const imgPane = el("div", { class: "rv-imgpane" });
  const imgBox = el("div", { class: "rv-imgbox" });
  imgPane.append(imgBox);
  // the ONLY floating control: the rotate press (the zoom buttons are gone
  // — fingers pinch, and the buttons got in the way, user 2026-08-16). The
  // rotate turns the VIEW instantly and queues the correction (the DESIRED
  // rotation, no image) — it commits on navigation and syncs when the
  // archive's computer is reachable (the arbiter cannot read cursive — an
  // upside-down page passes review; the fix must correct the pipeline's
  // data, not just the view)
  const zoomControls = el("div", { class: "rv-zoom" }, [
    el("button", { class: "rv-zoom-btn", onclick: () => rotatePage(session), title: "Turn the page" }, "↻"),
    el("button", {
      class: "rv-zoom-btn",
      onclick: () => {
        session.readRotation = 0;
        session.view = null;
        renderView(session);
        if (session.contentTop !== undefined) initialView(session, session.contentTop ?? 0);
      },
      title: "Return to the line you were reading",
    }, "⌖"),
  ]);
  imgPane.append(zoomControls);
  imgPane.append(
    el(
      "div",
      { class: "rv-legend" },
      "Red words are ones the machine wasn't sure of. Check them against the letter and fix them if they're wrong.",
    ),
  );

  const txBody = el("div", { class: "rv-txb" });
  const txPane = el("div", { class: "rv-txpane" }, [txBody]);
  const split = el("div", { class: "rv-split" }, [imgPane, txPane]);
  // the dual-pane link (user, 2026-08-16): scrolling the words pans the
  // picture so they stay matched (the reverse runs inside renderView)
  txBody.addEventListener("scroll", () => syncImageFromTx(session));
  // clicking AWAY from a line accepts the open edit (user, 2026-08-16: one
  // click edits, a click away accepts — the line's own click handles
  // itself and stops propagation)
  txBody.addEventListener("click", (e) => {
    if (e.target.closest(".rv-line")) return;
    acceptEdit(session);
  });
  // The boxes are touchable (the overlay's own click handler) — the
  // image pane itself does not start edits (2026-08-17: walkthrough
  // finding — tapping the picture silently edited the text).

  // The orientation fix's async half: while the backend re-reads the page's
  // text on the corrected image, the document is greyed with a note and the
  // confirm is blocked — the old text was read from the wrong-way page and
  // is unreliable (2026-08-16: page-02's first line read "At last venture
  // this form is the building of a" vs the corrected page's "A new venture
  // this term is the holding of a"). The reviewer navigates on; a poll
  // refreshes the page when the re-read lands.
  const pageState = (batch.processing || {})[page];
  // The re-read's async state, stated honestly (PRD VR10 AC12/AC14): a page
  // being re-read, or one whose re-read failed, is flagged — the text was
  // read before the page's orientation changed, so it may be stale until the
  // re-read lands. Never blames a correction the reviewer didn't make.
  if (pageState === "transcribing" || pageState === "failed") {
    const note = el(
      "div",
      { class: "rv-note rv-note--fixing" },
      pageState === "transcribing"
        ? "Re-reading this page's text — it was read before the page's orientation changed. You can review another document meanwhile."
        : "This page's re-read failed — the reading model was unreachable. The text below may be stale.",
    );
    if (pageState === "failed") {
      note.append(
        el("button", { class: "rv-btn rv-btn--ghost", onclick: () => rereadPage(session) }, "Re-read the page"),
      );
    }
    txPane.prepend(note);
  }
  session.pageProcessing = pageState;

  // Fail-fast (2026-08-17): a page whose layout failed validation is
  // never shown with wrong boxes — the boxes are withheld and the reason
  // is stated loudly. The reviewer must never see boxes that don't
  // correspond to the page.
  const layoutError = doc.layout_errors?.[page];
  if (layoutError) {
    txPane.prepend(
      el(
        "div",
        { class: "rv-note rv-note--fixing" },
        `This page's word boxes were rejected (${String(layoutError).slice(0, 120)}…) — showing the text without boxes.`,
      ),
    );
  }

  // the honest label: only the LAST page's press confirms — earlier pages
  // just advance (walk finding 3, 2026-08-15); the page rail is the pager.
  // The "Next flagged" button is GONE (user, 2026-08-17): the page chips
  // carry the flag dots — the reviewer taps the flagged chip to jump.
  const isLastPage = session.pageIndex === doc.pages.length - 1;
  const skipBtn = el(
    "button",
    { class: "rv-btn rv-btn--ghost", onclick: () => skipNext(session), title: "Move on without confirming — come back later" },
    "Skip →",
  );
  const rejectBtn = el(
    "button",
    { class: "rv-btn rv-btn--ghost", onclick: () => rejectDoc(session), title: "Move this document to the bin — it can be recovered" },
    "Bin →",
  );
  const confirmBtn = el(
    "button",
    { class: "rv-btn rv-btn--primary", onclick: () => confirmNext(session), disabled: session.pageProcessing === "transcribing" },
    isLastPage ? "✓ Confirm & Next →" : "Next page →",
  );
  const actionBar = el("div", { class: "rv-txa" }, [
    skipBtn,
    rejectBtn,
    el("div", { class: "rv-txa-right" }, [confirmBtn]),
  ]);

  root.append(topbar, rotate, split, actionBar);
  main.replaceChildren(root);

  session.root = root;
  session.txBody = txBody;
  session.confirmBtn = confirmBtn;
  session.fixingNote = null;
  syncSurfaceUrl(session);
  currentSession = session;
  updateFixingState(session);

  // the poll: while the backend re-reads this page's text, refresh when the
  // re-read lands (the old transcription is replaced, the stale edits
  // cleared, the flags recomputed from the new self-report)
  clearInterval(session.processingTimer);
  session.processingTimer = null;
  if (pageState === "transcribing") {
    session.processingTimer = setInterval(async () => {
      try {
        const data = await (
          await fetch(`/api/sync/batch/${encodeURIComponent(batch.batchId)}/drafts`, {
            headers: { Accept: "application/json" },
          })
        ).json();
        if ((data.processing || {})[page] || !Array.isArray(data.documents)) return;
        delete session.edits[page];
        saveEdits(batch.batchId, docIndex, session.edits);
        session.from = null;
        session.batch.documents = data.documents;
        session.batch.processing = data.processing || {};
        renderSurface(session.root, session);
      } catch {
        // backend unreachable — retry next tick
      }
    }, 5000);
  }

  renderTx(session);
  openViewer(session, imgBox);
}

// -- the page-image viewer: a plain <img> in a transform-scaled layer --------
// (2026-08-16: OpenSeadragon 6.1.0's tile pipeline never renders in the
// headless browsers verification uses, and the surface only exercises a
// fraction of it — a band of one jpeg, pinned boxes, drag-pan, three zoom
// buttons. The plain viewer paints in ANY browser — an <img> and a CSS
// transform — so a screenshot can verify the actual pixels. The view is a
// rectangle in DISPLAY pixels: the rotated image's own axes, so rotation
// turns the image AND the boxes together.)

/** The rotation's display frame: display = R·original + (ox, oy), the
 *  image's rotated bounding box in display px (dw × dh). 90° multiples. */
export function displayFrame(rotation, w, h) {
  switch (((rotation % 360) + 360) % 360) {
    case 90:
      return { a: 0, b: 1, c: -1, d: 0, ox: h, oy: 0, dw: h, dh: w };
    case 180:
      return { a: -1, b: 0, c: 0, d: -1, ox: w, oy: h, dw: w, dh: h };
    case 270:
      return { a: 0, b: -1, c: 1, d: 0, ox: 0, oy: w, dw: h, dh: w };
    default:
      return { a: 1, b: 0, c: 0, d: 1, ox: 0, oy: 0, dw: w, dh: h };
  }
}

/** A line box (original px [x0, y0, x1, y1]) → its bounding rect in the
 *  display frame. */
export function boxToDisplay(frame, box) {
  const xs = [frame.a * box[0] + frame.c * box[1] + frame.ox, frame.a * box[2] + frame.c * box[3] + frame.ox];
  const ys = [frame.b * box[0] + frame.d * box[1] + frame.oy, frame.b * box[2] + frame.d * box[3] + frame.oy];
  return { x: Math.min(...xs), y: Math.min(...ys), width: Math.abs(xs[1] - xs[0]), height: Math.abs(ys[1] - ys[0]) };
}

/** The band's anchor: the writing's top in page px — the first line box,
 *  or (when the content association found no boxes — page-02's cursive
 *  defeats the rec model) the detector's first unmatched line: its
 *  geometry is real even though no confident text anchor exists
 *  (tools/layout.py: "their geometry is real; a confident text anchor is
 *  not"). 0 when nothing is known (a blank page). */
export function bandAnchor(layout) {
  const boxTops = (layout?.lines || []).filter((l) => l.box).map((l) => l.box[1]);
  if (boxTops.length) return Math.min(...boxTops);
  const detTops = (layout?.unmatched || []).map((u) => u.box?.[1]).filter((y) => y !== undefined);
  return detTops.length ? Math.min(...detTops) : 0;
}

/** Half the topmost box's height: the margin the band anchor and pan floor
 *  need so the page's FIRST line is reachable, not clipped. The rec's
 *  detection boxes sit a fraction of a line BELOW the true ink tops (the
 *  top line is often merged into the next line's taller box — page-05's
 *  first line had no box at all, its ink 83px above the topmost box;
 *  page-02's cursive first line is 60px below its ink), so an anchor at
 *  the topmost box's own top clips the first line and the pan floor hides
 *  it entirely (user 2026-08-16: "the image won't let me scroll up at
 *  all"). Half a line covers the observed shifts; the writing still
 *  dominates the view above it. */
export function bandMargin(layout) {
  const boxes = (layout?.lines || []).filter((l) => l.box);
  if (!boxes.length) return 0;
  const top = boxes.reduce((a, b) => (a.box[1] <= b.box[1] ? a : b));
  return (top.box[3] - top.box[1]) / 2;
}

/** The view that shows ``rect`` (display px) in a pane: the rect fills one
 *  dimension, the pane's aspect rules the other (fitBounds semantics). */
export function fitRect(paneW, paneH, rect) {
  const paneAspect = paneW / paneH;
  const rectAspect = rect.width / rect.height;
  if (rectAspect >= paneAspect) {
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.width / paneAspect };
  }
  return { x: rect.x, y: rect.y, width: rect.height * paneAspect, height: rect.height };
}

/** Zoom the view by ``k`` around the pane point (cx, cy) — the image point
 *  under the cursor stays put. The visible width is clamped to
 *  [1/8, 8]× the image's display width (OSD's maxZoomPixelRatio 8). */
export function zoomView(view, k, paneW, paneH, cx, cy, imgW) {
  const s = paneW / view.width;
  const ix = view.x + cx / s;
  const iy = view.y + cy / s;
  const width = Math.min(Math.max(view.width / k, imgW / 8), imgW * 8);
  const height = (width * paneH) / paneW;
  const s2 = paneW / width;
  return { x: ix - cx / s2, y: iy - cy / s2, width, height };
}

/** Paint the current view: the layer's transform maps original-image points
 *  to the pane with the view's rectangle at the pane's origin. */
function renderView(session) {
  const { imgBox, layer, view, imgSize } = session;
  if (!view || !imgSize || !layer) return;
  const paneW = imgBox.clientWidth;
  const paneH = imgBox.clientHeight;
  if (!paneW || !paneH) return;
  const s = paneW / view.width;
  const display = viewRotation(session); // the ↻ + the per-line read rotation
  const f = displayFrame(display, imgSize.w, imgSize.h);
  layer.style.transform = `translate(${(f.ox - view.x) * s}px, ${(f.oy - view.y) * s}px) scale(${s}) rotate(${display}deg)`;
  syncTxFromImage(session); // the dual-pane link: the words follow the picture
}

function paneScale(session) {
  return session.imgBox.clientWidth / session.view.width;
}

function fitBounds(session, rect) {
  const imgBox = session.imgBox;
  session.view = fitRect(imgBox.clientWidth, imgBox.clientHeight, rect);
  renderView(session);
}

/** The page-image pane: the plain <img> with the detector's line boxes as
 *  absolutely-positioned guides inside a transform-scaled layer
 *  (2026-08-16: replaces OpenSeadragon — see the block comment above). */
function openViewer(session, imgBox) {
  const { batch, docIndex, pageIndex } = session;
  const doc = batch.documents[docIndex];
  const page = doc.pages[pageIndex];
  const layout = doc.layouts?.[page] || null;

session.resizer?.disconnect();
  session.imgBox = imgBox;
  session.layer = null;
  session.img = null;
  session.imgSize = null;
  session.view = null;
  session.overlays = [];
  session.contentTop = 0;
  session.userMoved = false;
  session.readRotation = 0; // the per-line read rotation resets per page

  const layer = el("div", { class: "rv-layer" });
  const img = el("img", { class: "rv-page", alt: "" });
  layer.append(img);
  imgBox.append(layer);
  session.layer = layer;
  session.img = img;

  img.onload = () => {
    session.imgSize = { w: img.naturalWidth, h: img.naturalHeight };
    // The layer's coordinate system is IMAGE pixels: it must be explicitly
    // sized to the image, or the absolute-position shrink-to-fit caps it at
    // the pane width and the transform scales it AGAIN — the letter renders
    // at pane×scale px, a 5× sliver pushed off-pane (walk finding, 2026-08-16:
    // ElaineWalksReview2 measured the rendered <img> at 95×173px in a
    // 491×595px pane — "the letter's not there"). The phone's "still not
    // visible" was this, all along.
    layer.style.width = `${img.naturalWidth}px`;
    layer.style.height = `${img.naturalHeight}px`;
    if (layout) {
      layout.lines.forEach((line) => {
        if (!line.box) return;
        // a positional box (2026-08-16: the content association found no
        // text anchor — the fallback assigned the next unmatched detection
        // in reading order) renders dashed: the geometry is real, the line
        // alignment is approximate — the reviewer must see the difference
        const box = el("div", { class: "rv-lb" + (line.box_source === "positional" ? " rv-lb--pos" : "") });
        box.dataset.line = String(line.index);
        box.style.left = `${line.box[0]}px`;
        box.style.top = `${line.box[1]}px`;
        box.style.width = `${line.box[2] - line.box[0]}px`;
        box.style.height = `${line.box[3] - line.box[1]}px`;
        layer.append(box);
        box.addEventListener("click", (e) => {
          e.stopPropagation();
          const idx = Number(box.dataset.line);
          if (!isNaN(idx)) {
            // keep the same page — the box is on this page
            session.selLine = idx;
            session.editing = null;
            // scroll the text to this line
            const txLine = session.txBody?.querySelector(`.rv-line[data-index="${idx}"]`);
            if (txLine) txLine.scrollIntoView({ block: "nearest" });
            // rotate to the line's reading orientation
            const doc = session.batch.documents[session.docIndex];
            const page = doc.pages[session.pageIndex];
            const line = doc.layouts?.[page]?.lines.find((l) => l.index === idx);
            if (line) session.readRotation = line.orientation || 0;
            renderView(session);
            renderTx(session);
          }
        });
        session.overlays.push(box);
      });
      session.overlays.forEach((box) => {
        box.classList.toggle("rv-lb--sel", box.dataset.line === String(session.selLine));
      });
      // the page's writing starts at the first line box — the initial band
      // anchors there (the top margin is blank, user 2026-08-16); a page
      // whose content association found no boxes anchors at the detector's
      // first line instead (page-02 — the rec model cannot read its cursive).
      // The anchor gets a HALF-LINE margin: the rec's detection boxes sit
      // below the true ink tops (page-05's first line "piano-practising
      // facilities. At the" had NO box — its ink starts 83px above the
      // topmost box; page-02's is 60px above), so without the margin the
      // first line's top is clipped and the pan floor hides it entirely —
      // the image "wouldn't let me scroll up at all" (user 2026-08-16).
      session.contentTop = bandAnchor(layout) - bandMargin(layout);
    }
    // Restore the resume position (2026-08-18): the scroll, image view,
    // selected line, and read rotation from the last session on this page.
    const saved = loadResumePosition(batch.batchId, page);
    if (saved && saved.docIndex === docIndex && saved.selLine !== undefined) {
      session.selLine = saved.selLine;
      session.visibleLine = saved.selLine;
      session.readRotation = saved.readRotation ?? session.readRotation;
      if (saved.view) {
        session.view = saved.view;
        session.contentTop = saved.view.y;
      } else {
        initialView(session, session.contentTop);
      }
      // RenderView fires syncTxFromImage which sets scrollTop from the
      // image view. We set the scrollTop AFTER renderView so our saved
      // scroll position wins (2026-08-18: walkthrough 3 found that
      // syncTxFromImage pulled the text back to the top).
      if (session.view) renderView(session);
      session.txBody.scrollTop = saved.scrollTop ?? 0;
      // Highlight the selected line without a full renderTx (which would
      // reset the scroll position). The existing text elements are already
      // in the DOM from renderSurface's renderTx call.
      if (saved.selLine !== null) {
        const prev = session.txBody.querySelector(".rv-line--sel");
        if (prev) prev.classList.remove("rv-line--sel");
        const txLine = session.txBody.querySelector(`.rv-line[data-index="${saved.selLine}"]`);
        if (txLine) txLine.classList.add("rv-line--sel");
      }
    } else if (session.selLine !== null) {
      initialView(session, session.contentTop);
      // The fit MUST paint before the pan — syncImageFromTx returns early
      // when the y already matches (no render!), leaving the layer
      // untransformed (2026-08-22: the first visit showed the image at
      // natural size — the blank top-left — "no text visible").
      renderView(session);
      syncImageFromTx(session);
    } else {
      initialView(session, session.contentTop);
      renderView(session);
    }
  };
  img.onerror = () => {
    layer.remove();
    imgBox.append(el("div", { class: "rv-note" }, "Could not load the page image."));
  };
  img.src = `/api/sync/batch/${encodeURIComponent(batch.batchId)}/page/${encodeURIComponent(page)}`;

  // The pane is HIDDEN while portrait shows the rotate prompt — a fit at
  // open measures a 0-sized pane and lands wrong (the letter becomes a
  // microscopic strip, user 2026-08-16). Re-fit when the pane resizes to a
  // genuinely visible size, but never fight the reviewer's own pans/zooms
  // after that.
  session.resizer = new ResizeObserver(() => {
    if (session.selLine !== null || session.userMoved) return;
    if (imgBox.clientHeight <= 0) return;
    const size = [imgBox.clientWidth, imgBox.clientHeight];
    if (session.lastFitSize && size[0] === session.lastFitSize[0] && size[1] === session.lastFitSize[1]) return;
    if (session.imgSize) {
      initialView(session, session.contentTop ?? 0);
      // The re-fit must PAINT — the onload's fit may have hit the hidden
      // 0-sized pane and returned without rendering, and this resize is
      // the pane becoming visible (2026-08-22: the first visit showed the
      // image at natural size — the blank top-left — "no text visible").
      renderView(session);
    }
  });
  session.resizer.observe(imgBox);

  // Drag to pan, pinch to zoom — pointer events give the persona's touch
  // and the tester's mouse the same path (touch-action: none keeps the
  // browser from hijacking the pan into a scroll). The move/up listeners
  // live on window so the drag survives the pointer leaving the pane —
  // and the flow works where pointer capture is flaky (2026-08-16: the
  // verification browser drops the move/up stream after a capture call).
  const pointers = new Map();
  let dragStart = null;
  let pinchStart = null;
  const onMove = (e) => {
    if (!pointers.has(e.pointerId) || !session.view) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 1 && dragStart) {
      const s = paneScale(session);
      session.view.x = dragStart.view.x - (e.clientX - dragStart.x) / s;
      session.view.y = dragStart.view.y - (e.clientY - dragStart.y) / s;
      clampView(session); // never pan into the margins (user 2026-08-16)
      session.userMoved = true;
      renderView(session);
    } else if (pointers.size === 2 && pinchStart && session.imgSize) {
      const [a, b] = [...pointers.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const k = pinchStart.dist ? dist / pinchStart.dist : 1;
      const rect = imgBox.getBoundingClientRect();
      const cx = (a.x + b.x) / 2 - rect.left;
      const cy = (a.y + b.y) / 2 - rect.top;
      const f = displayFrame(viewRotation(session), session.imgSize.w, session.imgSize.h);
      session.view = zoomView(session.view, k, imgBox.clientWidth, imgBox.clientHeight, cx, cy, f.dw);
      clampView(session); // never zoom off the page's edges
      pinchStart = { dist, view: { ...session.view } };
      session.userMoved = true;
      renderView(session);
    }
  };
  const onUp = (e) => {
    pointers.delete(e.pointerId);
    dragStart = null;
    pinchStart = null;
    if (!pointers.size) {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    }
  };
  const onDown = (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 1) {
      dragStart = { view: { ...session.view }, x: e.clientX, y: e.clientY };
      pinchStart = null;
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      dragStart = null;
      pinchStart = { dist: Math.hypot(a.x - b.x, a.y - b.y) };
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };
  imgBox.addEventListener("pointerdown", onDown);
  // clicking the image's text opens that line's edit (user 2026-08-16:
  // "the edit box should open if I click on the corresponding text on the
  // image"); a click on empty image (a margin) accepts the open edit. The
  // click after a real drag is suppressed by the browser (a moved drag is
  // not a click).
  imgBox.addEventListener("click", (e) => {
    e.stopPropagation(); // the imgPane's click-away must not fight this
    if (!session.view || !session.imgSize) return;
    const rect = imgBox.getBoundingClientRect();
    const s = paneScale(session);
    const imageX = session.view.x + (e.clientX - rect.left) / s;
    const imageY = session.view.y + (e.clientY - rect.top) / s;
    // the click must land INSIDE a line's box (x and y) — a click on the
    // blank margin is a click-away, not a selection (user 2026-08-16)
    const layout = doc.layouts?.[page];
    let idx = null;
    if (layout) {
      const f = displayFrame(viewRotation(session), session.imgSize.w, session.imgSize.h);
      for (const line of layout.lines) {
        if (!line.box) continue;
        const r = boxToDisplay(f, line.box);
        if (imageX >= r.x && imageX <= r.x + r.width && imageY >= r.y && imageY <= r.y + r.height) {
          idx = line.index;
          break;
        }
      }
    }
    if (idx !== null) startEdit(session, idx);
    else acceptEdit(session);
  });
}

/** The line whose box's display-y range contains (or sits just below) the
 *  image y — the image-pane-to-transcription mapping (the dual-pane link's
 *  pure half, 2026-08-16). Exported for tests. */
export function lineIndexForY(layout, rotation, imgSize, y) {
  const f = displayFrame(rotation, imgSize.w, imgSize.h);
  let firstBelow = null;
  for (const line of layout.lines) {
    if (!line.box) continue;
    const rect = boxToDisplay(f, line.box);
    if (y >= rect.y && y <= rect.y + rect.height) return line.index;
    if (rect.y >= y && (firstBelow === null || rect.y < firstBelow)) firstBelow = line.index;
  }
  return firstBelow;
}

/** The transcription scrolled — pan the image so the top visible line's
 *  box sits near the pane's top, at the SAME zoom (user, 2026-08-16: the
 *  panes should show roughly the same text at once; and selecting must
 *  never zoom). */
function syncImageFromTx(session) {
  if (session.syncLock || !session.view || !session.imgSize) return;
  const txb = session.txBody;
  if (!txb) return;
  const { batch, docIndex, pageIndex } = session;
  const doc = batch.documents[docIndex];
  const page = doc.pages[pageIndex];
  const layout = doc.layouts?.[page];
  if (!layout) return;
  // the top visible line: the first whose CONTENT position crosses the
  // scroll — offsetTop is root-relative, scrollTop is content-relative,
  // so subtract the pane's own root offset (2026-08-16: comparing them
  // raw picked a line ~6 rows off on the phone — the panes drifted apart)
  const base = txb.offsetTop;
  let topEl = null;
  for (const el of txb.querySelectorAll(".rv-line")) {
    const contentPos = el.offsetTop - base;
    if (contentPos + el.offsetHeight > txb.scrollTop) {
      topEl = el;
      break;
    }
  }
  const topIndex = Number(topEl?.dataset.index);
  if (!isNaN(topIndex) && topIndex !== session.visibleLine) {
    session.visibleLine = topIndex;
    const doc = session.batch.documents[session.docIndex];
    const page = doc.pages[session.pageIndex];
    const line = doc.layouts?.[page]?.lines.find((l) => l.index === topIndex);
    const newOrientation = line?.orientation ?? 0;
    if (newOrientation !== session.readRotation) {
      session.readRotation = newOrientation;
      renderView(session);
    }
  }
  const line = layout.lines.find((l) => l.index === topIndex);
  if (!line?.box) return;
  const f = displayFrame(viewRotation(session), session.imgSize.w, session.imgSize.h);
  const rect = boxToDisplay(f, line.box);
  const margin = session.imgBox.clientHeight * 0.08;
  const y = Math.min(Math.max(rect.y - margin, 0), Math.max(f.dh - session.view.height, 0));
  if (Math.abs(session.view.y - y) < 4) return;
  // a LARGE movement (a selection jump, the initial align) eases out —
  // never a dislocating leap (P18); the per-event scroll-follow steps are
  // small and the 60fps scroll events smooth them, so the transition only
  // lags the follow (2026-08-16)
  if (Math.abs(session.view.y - y) > 150) {
    session.layer.classList.add("rv-layer--smooth");
    setTimeout(() => session.layer?.classList.remove("rv-layer--smooth"), 220);
  }
  session.syncLock = true;
  session.view.y = y;
  renderView(session);
  session.syncLock = false;
}

/** The image view moved — scroll the transcription so the line at the
 *  view's top is near the pane's top (the dual-pane link's other half).
 *  DIRECT, not smooth: the image drag is direct manipulation and must
 *  track 1:1 (P18 — no dislocating moves). The sync guard is held until
 *  the NEXT frame so the programmatic scroll's own events cannot re-trigger
 *  the image-side sync and fight the drag (2026-08-16: the guard cleared
 *  too early — the panes ping-ponged, "jumps about disconcertingly" — the
 *  established dual-pane pattern: isSyncing + requestAnimationFrame). */
export function lineScrollFor(viewY, layout, frame, offsets) {
  // The transcript shows the LINE at the image's view top (2026-08-22,
  // user: the proportional fraction "tracks along but doesn't display the
  // actual line from the image"). The physical y selects the line whose
  // box is there (the first below when the view sits in a gap), and the
  // transcript scrolls to THAT line's offset — the transcript's top is
  // the actual line from the image.
  const lines = layout?.lines || [];
  let firstBelow = null;
  let idx = null;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.box) continue;
    const rect = boxToDisplay(frame, line.box);
    if (viewY >= rect.y && viewY <= rect.y + rect.height) {
      idx = i;
      break;
    }
    if (rect.y >= viewY && (firstBelow === null || rect.y < firstBelow.y)) {
      firstBelow = { y: rect.y, i };
    }
  }
  if (idx === null && firstBelow !== null) idx = firstBelow.i;
  return idx === null ? 0 : (offsets[idx] ?? 0);
}

function syncTxFromImage(session) {
  if (session.syncLock || !session.view || !session.imgSize) return;
  const txb = session.txBody;
  if (!txb) return;
  const { batch, docIndex, pageIndex } = session;
  const doc = batch.documents[docIndex];
  const page = doc.pages[pageIndex];
  const layout = doc.layouts?.[page];
  if (!layout) return;
  const f = displayFrame(viewRotation(session), session.imgSize.w, session.imgSize.h);
  const base = txb.offsetTop;
  const offsets = [...txb.querySelectorAll(".rv-line")].map((el) => el.offsetTop - base);
  const target = lineScrollFor(session.view.y, layout, f, offsets);
  if (Math.abs(txb.scrollTop - target) < 2) return;
  session.syncLock = true;
  txb.scrollTop = target;
  requestAnimationFrame(() => {
    session.syncLock = false;
  });
}

/** Clamp the view to the content's bounds — a pan can never scroll off
 *  into the blank top margin (user, 2026-08-16: "it allows me to scroll
 *  off the top"). The y-floor is the writing's top (the band anchor); the
 *  rotated views' floor is the page's own top. */
function clampView(session) {
  if (!session.view || !session.imgSize) return;
  const f = displayFrame(viewRotation(session), session.imgSize.w, session.imgSize.h);
  session.view.x = Math.min(Math.max(session.view.x, 0), Math.max(f.dw - session.view.width, 0));
  const floor = viewRotation(session) % 180 === 0 ? Math.max(session.contentTop ?? 0, 0) : 0;
  session.view.y = Math.min(Math.max(session.view.y, floor), Math.max(f.dh - session.view.height, floor));
}

/** The whole page back in view — the initial fit and the pane-resize
 *  re-fit (the Fit button is gone, user 2026-08-16 — fingers pinch). The
 *  band is pane-aware: on a short pane (the phone) it fits the letter's
 *  WIDTH — the readable view; on a tall pane the whole page. The content
 *  band is a rot-0 notion — after a rotation, fit the whole page. */
function fitPage(session, { markMoved = true } = {}) {
  if (!session.imgSize) return;
  if (markMoved) session.userMoved = true;
  const f = displayFrame(viewRotation(session), session.imgSize.w, session.imgSize.h);
  const imgBox = session.imgBox;
  const paneAspect = imgBox.clientWidth / Math.max(imgBox.clientHeight, 1);
  if (viewRotation(session) % 180 === 0 && paneAspect > (f.dw / f.dh) * 1.5) {
    // the band whose WIDTH is the page's width and whose aspect matches the
    // pane — fitBounds fits both dims, so the page fills the pane's width
    const visibleH = f.dw / paneAspect;
    // anchor the band at the writing, clamping to the page bounds
    const bandTop = Math.min(Math.max(session.contentTop ?? 0, 0), Math.max(f.dh - visibleH, 0));
    fitBounds(session, { x: 0, y: bandTop, width: f.dw, height: visibleH });
  } else {
    fitBounds(session, { x: 0, y: 0, width: f.dw, height: f.dh });
  }
}

/** Turn the page 90° — a LOCAL view rotation, committed later (2026-08-16:
 *  the front and back end are different boxes and the backend may be off,
 *  so the press never waits on it: the view rotates instantly, and the
 *  correction — the DESIRED rotation, not the image — queues on
 *  navigation and syncs when the backend is reachable. Multiple presses
 *  coalesce (the intent is the final rotation, so a half-corrected first
 *  press never triggers a reprocess), and a wrong correction is just
 *  another intent the backend applies as a delta. */
function rotatePage(session) {
  if (!session.imgSize) return;
  session.userMoved = true;
  // Only pressing ↻ reorients: step the DESIRED absolute orientation up one
  // quarter-turn, persist it, re-derive the display delta. The desired is
  // self-contained (never a carried session delta), so there is nothing to
  // accumulate across visits.
  const { batchId, page } = currentPage(session);
  const base = session.desired ?? baseQuarters(session.baseRotation);
  session.desired = (base + 1) % 4;
  session.rotation = deltaOfDesired(session.desired, session.baseRotation);
  // The view-only rotate rule (VR15, 2026-08-17): a desired orientation
  // the pipeline already READ rotates the view only — nothing owed, no
  // re-read queued. An uncovered orientation is the signal the first pass
  // missed something: the correction stays owed (acked unchanged) and the
  // backend re-reads it (the second pass does better).
  const doc = session.batch.documents[session.docIndex];
  const covered = doc?.orientations?.[page];
  if (isOrientationCovered(covered, session.baseRotation, session.desired)) {
    session.acked = session.desired;
    saveOrientation(batchId, page, { desired: session.desired, acked: session.desired });
  } else {
    saveOrientation(batchId, page, { desired: session.desired, acked: session.acked });
  }
  // re-fit the view for the rotated frame — the view rect lives in the
  // previous frame's coordinates, and rendering it through the new frame
  // drew the page in the wrong place, unreadable (user 2026-08-16: "it's
  // not drawn in the right place after I rotate it")
  session.readRotation = 0; // the reviewer's own ↻ overrides the per-line read rotation
  fitPage(session, { markMoved: false });
  updateFixingState(session);
}

/** The in-place fixing state: the waiting note + the confirm gate follow
 *  an OWED correction (desired != acked — a reorientation not yet delivered
 *  to, and confirmed by, the backend) and the backend's reprocess state. The
 *  displayed orientation is always the desired one regardless (VR10) — the
 *  note is about the text, which is stale until the re-read lands. */
function updateFixingState(session) {
  const waiting = (session.desired ?? 0) !== (session.acked ?? 0);
  const fixing = waiting || session.pageProcessing === "transcribing";
  if (session.confirmBtn) session.confirmBtn.disabled = fixing;
  const note = session.fixingNote;
  if (waiting && !note) {
    session.fixingNote = el(
      "div",
      { class: "rv-note rv-note--fixing" },
      "The page's rotation is waiting to reach the archive's computer — the text below was read before your rotation and will be re-read.",
    );
    session.root.querySelector(".rv-txpane")?.prepend(session.fixingNote);
  } else if (!waiting && note) {
    note.remove();
    session.fixingNote = null;
  }
}

/** The current (batch id, page name) the session is showing. */
function currentPage(session) {
  const doc = session.batch.documents[session.docIndex];
  return { batchId: session.batch.batchId, page: doc.pages[session.pageIndex] };
}

/** The backend's applied rotation as whole quarter-turns (0-3). */
function baseQuarters(baseDeg) {
  return Math.round(baseDeg / 90) % 4;
}

/** Whether the pipeline has already READ the page at the reviewer's
 *  DESIRED orientation — the view-only rotate rule (2026-08-17, VR15):
 *  the covered set is the layout's per-line orientations, relative to
 *  the served image; the desired is absolute quarter-turns, so the set
 *  shifts by the backend's applied rotation. A covered rotate changes
 *  only the view (no queued re-read); an uncovered one queues the old
 *  path — the reviewer's rotate is the signal the first pass missed an
 *  orientation. A page with no layout (no entry) covers nothing. */
export function isOrientationCovered(covered, baseDeg, desiredQuarters) {
  if (!Array.isArray(covered) || covered.length === 0) return false;
  const base = baseQuarters(baseDeg);
  const absolute = new Set(covered.map((deg) => (Math.round(deg / 90) + base) % 4));
  return absolute.has(desiredQuarters);
}

/** The CSS rotation (degrees) that shows the reviewer's DESIRED orientation
 *  on top of the served image — the desired absolute minus the backend's
 *  applied rotation. Deterministic and self-contained (VR10). */
export function deltaOfDesired(desiredQuarters, baseDeg) {
  return (((desiredQuarters * 90 - (baseDeg ?? 0)) % 360) + 360) % 360;
}

/** The combined display rotation: the reviewer's desired orientation plus
 *  the per-line read rotation (2026-08-17: selecting a line whose text
 *  runs sideways turns the view so that line reads horizontally — a pure
 *  view change, never an owed correction, so the ↻ state is untouched). */
export function viewRotation(session) {
  return (((session.rotation ?? 0) + (session.readRotation ?? 0)) % 360 + 360) % 360;
}

// -- the reviewer's desired orientation (display truth) + the delivery
//    obligation. The front end never consumes its own delivery queue to
//    decide what to display: display reads the stored `desired` (set only
//    by a ↻ press); delivery is outbound and committed on navigation. -----

/** A page being reworked on the backend: its transcription re-read is in
 *  flight (the async treat after a rotate) — it must not appear in the
 *  review flow until the backend has updated it (user 2026-08-16: "it
 *  shouldn't have shown me it at all once we'd established that it needed
 *  rework on the back end"). A page the reviewer merely reoriented is
 *  shown as its desired orientation (VR10) — reworking is about the text,
 *  not the orientation. */
export function isReworking(batch, page) {
  return (batch?.processing || {})[page] === "transcribing";
}

/** The flagged positions the reviewer can act on — the rework pages'
 *  positions are excluded (their flags will change when the backend
 *  re-reads them). */
function availablePositions(session) {
  return flaggedPositions(session.batch.documents, session.docIndex, session.edits).filter(
    (p) => !isReworking(session.batch, p.page),
  );
}

/** The next available page index strictly AFTER ``from`` (never backward —
 *  a wrap would loop the confirm on a doc whose tail is all reworking);
 *  -1 when the rest of the document is being reworked. */
function nextAvailableAfter(doc, batch, from) {
  for (let i = from + 1; i < doc.pages.length; i++) {
    if (!isReworking(batch, doc.pages[i])) return i;
  }
  return -1;
}

const ORIENT_KEY = "loft-review-orientations";

/** The persisted reviewer orientation for a page: { desired, acked } in
 *  quarter-turns (0-3), or null when the page has never been rotated
 *  (display then defaults to the backend orientation). `desired` is set
 *  only by a ↻ press; `acked` is the last desired the backend confirmed. */
export function orientationState(batchId, page) {
  try {
    const m = JSON.parse(localStorage.getItem(ORIENT_KEY) || "{}") || {};
    return m[`${batchId}|${page}`] ?? null;
  } catch {
    return null;
  }
}

/** Persist { desired, acked } for a page. Passing acked = desired is how a
 *  delivered correction is acknowledged (nothing owed). */
export function saveOrientation(batchId, page, state) {
  let m = {};
  try {
    const stored = JSON.parse(localStorage.getItem(ORIENT_KEY) || "{}");
    if (stored && typeof stored === "object") m = stored;
  } catch {
    // corrupt storage — start fresh from the empty map
  }
  const key = `${batchId}|${page}`;
  if (state.desired == null) m[key] = null;
  else m[key] = { desired: state.desired, acked: state.acked ?? state.desired };
  if (m[key] == null) delete m[key];
  localStorage.setItem(ORIENT_KEY, JSON.stringify(m));
}

/** Push the queued corrections to the backend (the fast rotation applies
 *  there; the slow re-transcription runs as its async job). Drop each
 *  intent once the backend records it. Returns whether anything was
 *  delivered. */
/** Commit the current page's owed reorientation: if the reviewer's desired
 *  orientation is not yet acknowledged by the backend, deliver it (the
 *  rotate route applies an idempotent delta — a retried intent is a no-op)
 *  and ack on success. Outbound only: the delivery state is never read back
 *  into the display. A failed delivery leaves `acked` unchanged, so the
 *  next commit retries (VR8 reliability). */
async function queueRotation(session) {
  const { batchId, page } = currentPage(session);
  const st = orientationState(batchId, page);
  if (!st || st.desired === st.acked) return; // nothing owed
  try {
    const res = await fetch(
      `/api/sync/batch/${encodeURIComponent(batchId)}/page/${encodeURIComponent(page)}/rotate`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ quarters: st.desired }) },
    );
    if (!res.ok) throw new Error(`rotate rejected (${res.status})`);
    // acknowledged — the backend has applied the rotation to its image
    session.acked = st.desired;
    saveOrientation(batchId, page, { desired: st.desired, acked: st.desired });
    updateFixingState(session);
    // refresh the drafts so the reprocess state (grey-out note) and the
    // corrected layout surface; best-effort
    try {
      const data = await (
        await fetch(`/api/sync/batch/${encodeURIComponent(batchId)}/drafts`, { headers: { Accept: "application/json" } })
      ).json();
      if (Array.isArray(data.documents)) {
        session.batch.documents = data.documents;
        session.batch.processing = data.processing || {};
      }
    } catch {
      // the refetch is best-effort — the next visit refreshes
    }
  } catch {
    // backend unreachable — acked unchanged, so it stays owed and the next
    // commit retries (idempotent backend makes a duplicate delivery a no-op)
  }
}

/** Deliver every OWED reorientation to the backend (the reliable half of
 *  the rotate seam): one attempt whenever the app opens a batch list, ack
 *  on success, leave owed on failure (retried next open/commit). Outbound
 *  only — it never feeds the display, so it cannot reorient anything. It is
 *  safe BECAUSE an entry exists only for a page the reviewer actually
 *  pressed (VR10 AC13): a page with no stored desired owes nothing, so a
 *  stale value cannot be replayed. */
export async function deliverOwed() {
  let m = {};
  try {
    const stored = JSON.parse(localStorage.getItem(ORIENT_KEY) || "{}");
    if (stored && typeof stored === "object") m = stored;
  } catch {
    // corrupt storage — nothing owned
  }
  for (const [key, s] of Object.entries(m)) {
    if (!s || s.desired == null || s.desired === s.acked) continue; // not owed
    const sep = key.indexOf("|");
    const batchId = key.slice(0, sep);
    const page = key.slice(sep + 1);
    try {
      const res = await fetch(
        `/api/sync/batch/${encodeURIComponent(batchId)}/page/${encodeURIComponent(page)}/rotate`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ quarters: s.desired }) },
      );
      if (!res.ok) throw new Error(`rotate rejected (${res.status})`);
      // acknowledge ONLY the delivery — the display keeps reading `desired`
      saveOrientation(batchId, page, { desired: s.desired, acked: s.desired });
    } catch {
      // backend unreachable — leave owed; retried on the next open/commit
    }
  }
}

/** Retry a failed re-read (PRD VR10 AC14): ask the backend to re-run the
 *  reprocess over the current image, then re-render. Orientation is
 *  untouched — this only re-runs OCR. */
async function rereadPage(session) {
  const { batchId, page } = currentPage(session);
  try {
    const res = await fetch(
      `/api/sync/batch/${encodeURIComponent(batchId)}/page/${encodeURIComponent(page)}/reread`,
      { method: "POST" },
    );
    if (!res.ok) return;
    const data = await (
      await fetch(`/api/sync/batch/${encodeURIComponent(batchId)}/drafts`, { headers: { Accept: "application/json" } })
    ).json();
    if (Array.isArray(data.documents)) {
      session.batch.documents = data.documents;
      session.batch.processing = data.processing || {};
    }
  } catch {
    // backend unreachable — the failed note stays; the reviewer can retry
  }
  const main = session.root?.parentElement;
  if (main) renderSurface(main, session);
}

/** The default view: on a short pane (the phone's horizontal split) the
 *  whole-page fit is a keyhole — fit the letter's WIDTH to the pane so a
 *  readable band shows and the reviewer pans vertically (walk finding 8,
 *  2026-08-15). The band is positioned at the page's CONTENT, not its top —
 *  a scanned page's top margin is blank, and the first fit showed empty
 *  paper (user 2026-08-16: "I don't see any of the actual document").
 *  Tall panes keep the whole page in view. Records the pane size it fitted
 *  against, so the resize handler can tell a real change from noise. */
/** The default view: show the FULL bounding box of all line boxes so the
 *  reviewer sees the entire card at once (the walkthrough finding — the
 *  postcard's header was visible but the message was off-screen and
 *  unreachable via pan). On very wide/thin pages the zoom fills the pane
 *  width with the full height visible. */
function initialView(session, contentTop = 0) {
  if (!session.imgSize) return;
  session.lastFitSize = [session.imgBox.clientWidth, session.imgBox.clientHeight];
  session.contentTop = contentTop;
  const doc = session.batch.documents[session.docIndex];
  const page = doc.pages[session.pageIndex];
  const layout = doc.layouts?.[page];
  const bounds = initialViewRect(layout) ?? contentBounds(layout);
  if (bounds) {
    const paneW = session.imgBox.clientWidth;
    const paneH = session.imgBox.clientHeight;
    session.view = fitRect(paneW, paneH, bounds);
  } else {
    fitPage(session, { markMoved: false });
  }
}

/** Highlight the line's box and the transcription line; the box list is
 *  re-rendered by the caller when the surface is static. */
function syncSelection(session, lineIndex) {
  session.selLine = lineIndex;
  session.visibleLine = lineIndex;
  session.editing = null;
  session.overlays.forEach((box) => {
    box.classList.toggle("rv-lb--sel", box.dataset.line === String(lineIndex));
  });
}

/** Accept the open edit — the user's model (2026-08-16): one click edits,
 *  a click away ACCEPTS; there is no separate save button. */
function acceptEdit(session) {
  if (session.editing === null) return;
  const input = session.txBody?.querySelector(".rv-wfi");
  if (input) {
    applyEdit(session, session.editing, input.value);
  } else {
    session.editing = null;
    renderTx(session);
  }
}

/** One click on a line enters edit mode (user, 2026-08-16 — no separate
 *  select-then-edit): the prior edit, if any, accepts first. The line's
 *  box stays highlighted and the dual-pane link keeps its image region in
 *  view at the same zoom (never a surprise zoom). */
function startEdit(session, lineIndex) {
  if (session.editing !== null && session.editing !== lineIndex) acceptEdit(session);
  syncSelection(session, lineIndex);
  session.editing = lineIndex;
  // the per-line read rotation: a line whose text runs sideways turns the
  // view so it reads horizontally (2026-08-17, VR15 — the postcard's 270°
  // message must be readable without pressing ↻). Pure view: the ↻ state
  // (desired/acked) is untouched.
  const doc = session.batch.documents[session.docIndex];
  const page = doc.pages[session.pageIndex];
  const line = doc.layouts?.[page]?.lines.find((l) => l.index === lineIndex);
  const orientation = line?.orientation ?? 0;
  // the pass at orientation D reads its text with the image rotated CSS D°
  // (pass_at rotates -D in PIL = D in CSS) — the display rotation is the
  // orientation itself, not its mirror (2026-08-17: (360-O) put the 270°
  // message upside down)
  session.readRotation = orientation;
  // Zoom the image to the focused line (2026-08-20 — the recorded "never
  // zoom" decision is superseded: the reviewer must SEE the line's
  // original at a readable scale, not just a same-zoom pan). The line
  // fills the pane with a margin; the read rotation is already in the
  // frame. A boxless line keeps the old turn-only view.
  if (line?.box && session.imgBox?.clientWidth && session.view) {
    const f = displayFrame(viewRotation(session), session.imgSize.w, session.imgSize.h);
    const rect = boxToDisplay(f, line.box);
    const pad = Math.max(rect.width, rect.height) * 0.04;
    fitBounds(session, {
      x: rect.x - pad,
      y: rect.y - pad,
      width: rect.width + 2 * pad,
      height: rect.height + 2 * pad,
    });
    clampView(session);
    session.userMoved = true; // a deliberate zoom — stop the auto-fit follow
  } else {
    renderView(session); // the view turns to read the line horizontally
  }
  renderTx(session);
}

/** Apply the line's corrected text — the line is now verified (its flags
 *  stop counting), the fix persists (resumable, VR9), and the flag tour
 *  continues AFTER this line (walk finding 2, 2026-08-15). */
function applyEdit(session, lineIndex, text) {
  const { batch, docIndex, pageIndex } = session;
  const doc = batch.documents[docIndex];
  const page = doc.pages[pageIndex];
  const layout = doc.layouts?.[page] || null;
  session.edits[page] = { ...(session.edits[page] || {}), [lineIndex]: text };
  session.from = { page, line: lineIndex }; // the tour continues AFTER this line (finding 2)
  saveEdits(batch.batchId, docIndex, session.edits);
  session.editing = null;
  session.selLine = lineIndex;
  renderTx(session);
  // The accept ADVANCES the review: a line down, eased, so the next
  // content comes into view — the reviewer never reads a line whose
  // original they can't see. The advance fires whenever the accepted line
  // is NOT the top visible row (a line above it is still in view): three
  // rows visible and the SECOND is ticked → scroll up a line so the next
  // line becomes the middle row and the image (through the dual-pane
  // link) shows its original centered (user 2026-08-16: "if I can see
  // three rows of transcription and I tick the second one, it should
  // scroll up a line, with nice animation and ease"). A TOP-row accept
  // holds — the next line is already the second row. Without any of this
  // the browser's scroll-anchoring (the edit row shrinks on accept)
  // drifted the view UP (user 2026-08-16, earlier).
  // The advance fires ONLY when the next line continues physically BELOW:
  // the page's marginal notes sit far ABOVE the reading order (line 28's
  // box at y2725 vs line 27's at y4142) — advancing to one yanked the
  // image "WAY up to quite near the beginning again" (user 2026-08-16).
  // A note's accept holds the view instead; the reviewer scrolls on.
  requestAnimationFrame(() => {
    const txb = session.txBody;
    const el = txb?.querySelector(".rv-line--sel");
    if (!txb || !el) return;
    const tRect = txb.getBoundingClientRect();
    const above = txb.querySelector(`.rv-line[data-index="${Number(el.dataset.index) - 1}"]`);
    const hasLineAbove = above ? above.getBoundingClientRect().bottom > tRect.top : false;
    if (!hasLineAbove) return; // the accepted line is the top visible row — hold
    const f = displayFrame(viewRotation(session), session.imgSize.w, session.imgSize.h);
    const current = layout?.lines.find((l) => l.index === Number(el.dataset.index));
    const next = layout?.lines.find((l) => l.index === Number(el.dataset.index) + 1);
    const curTop = current?.box ? boxToDisplay(f, current.box).y : null;
    const nextTop = next?.box ? boxToDisplay(f, next.box).y : null;
    if (nextTop === null || curTop === null || nextTop < curTop) return; // the next line is above — hold
    txb.scrollBy({ top: el.offsetHeight + 8, behavior: "smooth" });
  });
}

/** Mark a flagged line as CHECKED without changing its text — the line is
 *  verified (its flags stop counting) and the verbatim text stays in the
 *  confirmation (user, 2026-08-16: a line can be fine even with red
 *  squiggles on it). The shared verified path: the edit is the line's own
 *  text. */
function applyMarkedFine(session, lineIndex) {
  const { batch, docIndex, pageIndex } = session;
  const doc = batch.documents[docIndex];
  const page = doc.pages[pageIndex];
  const layout = doc.layouts?.[page];
  const line = layout?.lines.find((l) => l.index === lineIndex);
  if (!line) return;
  applyEdit(session, lineIndex, line.text);
}

/** Wrap the input's selection in a format marker (~~ strike, ~ underline)
 *  and keep the selection on the wrapped text — the edit row's format
 *  buttons (2026-08-16). With no selection, drop the markers at the cursor
 *  with the cursor between them. */
function wrapSelection(input, marker) {
  const s = input.selectionStart;
  const e = input.selectionEnd;
  const text = input.value;
  if (e > s) {
    input.value = text.slice(0, s) + marker + text.slice(s, e) + marker + text.slice(e);
    input.selectionStart = s + marker.length;
    input.selectionEnd = e + marker.length;
  } else {
    input.value = text.slice(0, s) + marker + marker + text.slice(s);
    input.selectionStart = input.selectionEnd = s + marker.length;
  }
  input.focus();
}

/** Render a token with its ~~struck~~ spans as line-through text — the
 *  VLM marks crossed-out words with tildes; the reviewer must see them as
 *  crossed out, not literal tildes (walk finding 5, 2026-08-15). */
/** Exported for tests: the format split of a token — ~~struck~~ (the
 *  crossed-out words) and ~underlined~ (underlined in the letter, user
 *  2026-08-16) — the surface renders them, never literal tildes. */
export function formatParts(text) {
  const parts = [];
  const re = /~~([^~]+)~~|~([^~]+)~/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), kind: null });
    parts.push({ text: m[1] ?? m[2], kind: m[1] !== undefined ? "struck" : "underlined" });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), kind: null });
  if (!parts.length) parts.push({ text, kind: null });
  return parts;
}

/** The ~~struck~~-only split (the flagged word buttons — an underlined
 *  word inside a flag is vanishingly rare). Kept for its tests. */
export function strikeParts(text) {
  return formatParts(text).map((p) => ({ text: p.text, struck: p.kind === "struck" }));
}

function wordNode(word, { flagged, onclick }) {
  const children = formatParts(word).map((p) =>
    p.kind === "struck"
      ? el("span", { class: "rv-struck" }, p.text)
      : p.kind === "underlined"
        ? el("span", { class: "rv-underlined" }, p.text)
        : p.text,
  );
  return flagged ? el("button", { class: "rv-wc", onclick }, children) : el("span", {}, children);
}

/** Render the transcription pane: verbatim lines, flagged words, the
 *  selected line highlighted, the editing line as an input. The scroll
 *  position survives the re-render — replacing the children resets it,
 *  which drifted the panes apart until the next scroll re-aligned them
 *  (user 2026-08-16: "the two views got out of sync somehow"). */
function renderTx(session) {
  const { batch, docIndex, pageIndex } = session;
  const doc = batch.documents[docIndex];
  const page = doc.pages[pageIndex];
  const layout = doc.layouts?.[page] || null;
  const pageEdits = session.edits[page] || {};
  // reconcile edits when the layout changed (different line indices, new
  // pipeline run) — stale edits are re-mapped by text or dropped (2026-08-18)
  const reconciled = reconcileEdits(pageEdits, layout);
  if (reconciled !== pageEdits) {
    session.edits[page] = reconciled;
    saveEdits(batch.batchId, docIndex, session.edits);
  }
  const txb = session.txBody;
  const savedScroll = txb?.scrollTop ?? 0;

  session.txBody.replaceChildren();
  const lines = layout
    ? layout.lines
    : (doc.texts?.[page] || "").split("\n").filter(Boolean).map((text, i) => ({ index: i, text, box: null, words: [] }));

  lines.forEach((line) => {
    const corrected = reconciled[line.index];
    const shown = corrected ?? line.text;
    const sel = session.selLine === line.index ? " rv-line--sel" : "";
    // one dense row: the text + the actions — no number gutter (the line
    // numbers ate screen real estate for nothing, user 2026-08-16: "why?")
    const lineEl = el("div", { class: `rv-line${sel}` });
    lineEl.dataset.index = String(line.index); // the dual-pane link's anchor

    if (session.editing === line.index) {
      const input = el("input", {
        class: "rv-wfi",
        value: shown,
        // enterkeyhint "done": the mobile keyboard's action key becomes
        // Done, which dismisses the keyboard (user 2026-08-16: "no get rid
        // of keyboard button on the keyboard — is that a setting?")
        enterkeyhint: "done",
        onkeydown: (e) => {
          if (e.key === "Enter") applyEdit(session, line.index, input.value);
          else if (e.key === "Escape") {
            // the one way OUT without accepting — the edit is discarded
            session.editing = null;
            renderTx(session);
          }
        },
      });
      lineEl.append(el("div", { class: "rv-wfw" }, [input]));

      // The format controls live IN the edit row — no floating menu
      // (2026-08-16: the platform's edit menu — cut/copy/paste/select-all —
      // appears on selection and cannot be suppressed or extended; a second
      // popup duplicating it was wrong — "two popups looking slightly
      // different"). The row adds what the platform cannot: the strike and
      // underline conventions. They apply to the current selection; with no
      // selection they drop the markers at the cursor.
      const strikeBtn = el("button", {
        class: "rv-fmtbtn rv-fmtbtn--row",
        title: "Strike through the selection (~~word~~)",
        onclick: (e) => { e.stopPropagation(); wrapSelection(input, "~~"); },
      }, "S̶");
      const underBtn = el("button", {
        class: "rv-fmtbtn rv-fmtbtn--row",
        title: "Underline the selection (~word~)",
        onclick: (e) => { e.stopPropagation(); wrapSelection(input, "~"); },
      }, "U");
      input.after(strikeBtn, underBtn);
      const doneBtn = el("button", {
        class: "rv-fmtbtn rv-fmtbtn--row",
        title: "Save correction (Enter)",
        onclick: (e) => { e.stopPropagation(); applyEdit(session, line.index, input.value); },
      }, "✓");
      const cancelBtn = el("button", {
        class: "rv-fmtbtn rv-fmtbtn--row",
        title: "Discard correction (Escape)",
        onclick: (e) => {
          e.stopPropagation();
          session.editing = null;
          renderTx(session);
        },
      }, "✕");
      input.after(doneBtn, cancelBtn);
      input.focus();
    } else {
      const textEl = el("span", { class: "rv-lt" });
      // An edited line shows the reviewer's OWN corrected text — the red
      // words are gone (the line is verified). The layout's word buttons
      // render only for lines the reviewer hasn't touched (walk finding 4,
      // 2026-08-16: the fix was stored but never displayed — "did it save
      // or not?").
      if (corrected !== undefined) {
        textEl.append(...formatParts(shown).map((p) =>
          p.kind === "struck"
            ? el("span", { class: "rv-struck" }, p.text)
            : p.kind === "underlined"
              ? el("span", { class: "rv-underlined" }, p.text)
              : p.text,
        ));
      } else if (line.words.length) {
        line.words.forEach((word, wi) => {
          const node = wordNode(word.word, {
            flagged: word.conf === 0,
            onclick: (e) => {
              e.stopPropagation(); // the line's own click would select and cancel the edit
              startEdit(session, line.index);
            },
          });
          textEl.append(node, wi < line.words.length - 1 ? " " : "");
        });
      } else {
        textEl.append(...formatParts(shown).map((p) =>
          p.kind === "struck"
            ? el("span", { class: "rv-struck" }, p.text)
            : p.kind === "underlined"
              ? el("span", { class: "rv-underlined" }, p.text)
              : p.text,
        ));
      }
      lineEl.append(textEl);
      // "mark this line fine" — a checked line needs no text change (user,
      // 2026-08-16: the verbatim text counts as verified). On EVERY line
      // (2026-08-17): the multi-orientation pages are provisional — the
      // reviewer checks each line as they read it. The button is a toggle:
      // ○ unchecked (not yet verified), ✓ checked (verified). Clicking a
      // checked line unchecks it (the edit is removed).
      const isChecked = corrected !== undefined || pageEdits[line.index] !== undefined;
      lineEl.append(
        el("button", {
          class: "rv-ok-btn" + (isChecked ? " rv-ok-btn--checked" : ""),
          title: isChecked ? "Mark this line as not checked" : "Mark this line as fine",
          onclick: (e) => {
            e.stopPropagation();
            if (isChecked) {
              // uncheck — remove the edit for this line
              const { batch, docIndex, pageIndex } = session;
              const page = doc.pages[pageIndex];
              const edits = { ...session.edits[page] };
              delete edits[line.index];
              session.edits[page] = edits;
              saveEdits(batch.batchId, docIndex, session.edits);
              renderTx(session);
            } else {
              applyMarkedFine(session, line.index);
            }
          },
        }, isChecked ? "✓" : "○"),
      );
      // every line is clickable — one click enters edit (user, 2026-08-16);
      // clicking the already-editing line's own input must not re-render
      lineEl.addEventListener("click", () => {
        if (session.editing === line.index) return;
        startEdit(session, line.index);
      });
    }
    session.txBody.append(lineEl);
  });
  // restore the scroll — a re-render of the same content must not move the
  // reader (P18: no dislocating moves); the selected line's scrollIntoView
  // below overrides it only when the SELECTION changed (an edit-accept of
  // the same line must not yank the view back to it)
  if (savedScroll > 0 && txb.scrollHeight > savedScroll) txb.scrollTop = savedScroll;
  if (session.selLine !== null && session.selLine !== session.lastSelRendered) {
    session.txBody.querySelector(".rv-line--sel")?.scrollIntoView({ block: "nearest" });
  }
  session.lastSelRendered = session.selLine;
}

/** Confirm & Next: the last page confirms the document through the sync
 *  seam (outbox fallback), then moves on; earlier pages just advance. The
 *  confirmation is blocked while the page's orientation fix is in flight
 *  (the text would be the stale pre-fix reading). */
/** Skip — advance WITHOUT confirming (user, 2026-08-17: the agreed
 *  replacement for the next-red-word button — a way to give up on
 *  something temporarily). The page, and on the last page the document,
 *  stays unconfirmed — the reviewer can come back to it. */
function skipNext(session) {
  acceptEdit(session);
  const { batch, docIndex } = session;
  const doc = batch.documents[docIndex];
  if (session.pageIndex < doc.pages.length - 1) {
    const next = nextAvailableAfter(doc, batch, session.pageIndex);
    session.pageIndex = next === -1 ? session.pageIndex + 1 : next;
    session.selLine = null;
    session.editing = null;
    renderSurface(session.root, session);
    return;
  }
  // the last page — the next document, nothing confirmed
  openReview(session.root, batch, (docIndex + 1) % batch.documents.length);
}

/** Reject — soft-delete to the recoverable bin (AC30). The document
 *  disappears from the pending list; the rejection is stored in
 *  localStorage and survives page reload. A future 'Bin' view will
 *  list rejected documents and offer a restore button. */
function rejectDoc(session) {
  acceptEdit(session);
  const { batch, docIndex } = session;
  const doc = batch.documents[docIndex];
  saveRejection(batch.batchId, docIndex);
  doc.status = "rejected";
  // advance to the next document still awaiting review
  const next = batch.documents.findIndex((d, i) => i > docIndex && d.status !== "confirmed" && d.status !== "rejected");
  if (next !== -1) {
    openReview(session.root, batch, next);
  } else {
    navigate(`review/${batch.batchId}`);
  }
}

async function confirmNext(session) {
  const { batch, docIndex } = session;
  const doc = batch.documents[docIndex];
  const page = doc.pages[session.pageIndex];
  const pageState = (batch.processing || {})[page];
  if (pageState === "transcribing" || (session.rotation ?? 0) !== 0) return;
  acceptEdit(session);
  await queueRotation(session);
  if (session.pageIndex < doc.pages.length - 1) {
    // advance to the next AVAILABLE page — a page being reworked on the
    // backend is skipped (the reviewer must get past it to the next one,
    // user 2026-08-16)
    const next = nextAvailableAfter(doc, batch, session.pageIndex);
    session.pageIndex = next === -1 ? session.pageIndex + 1 : next;
    session.selLine = null;
    session.editing = null;
    renderSurface(session.root, session);
    return;
  }
  const payload = {
    batch_id: batch.batchId,
    doc_index: docIndex + 1, // 1-based, matches the CLI gate
    pages: doc.pages,
    text: correctedDocumentText(doc, session.edits),
    status: "confirmed",
    confirmed_at: new Date().toISOString(),
  };
  const pushed = await confirmDocument(payload);
  if (pushed) clearEdits(batch.batchId, docIndex);
  doc.status = "confirmed";
  session.root
    .querySelector(".rv-txa")
    ?.replaceChildren(
      el(
        "div",
        { class: "rv-note rv-note--ok" },
        pushed
          ? `Document ${docIndex + 1} of ${batch.documents.length} saved to the family archive.`
          : "Saved on this device — will sync when the archive's computer is reachable.",
      ),
    );
  // advance to the next document still awaiting review — the confirmed/
  // rejected ones stay in the list with their done chips, so a raw
  // index+1 can land on one and reopen it as a fresh surface (bot
  // review, 2026-08-16)
  const next = batch.documents.findIndex((d, i) => i > docIndex && d.status !== "confirmed");
  if (next !== -1) {
    setTimeout(() => openReview(session.root, batch, next), 1800);
  } else {
    setTimeout(() => navigate(`review/${batch.batchId}`), 2200);
  }
}

// -- the view's own wiring (app.js calls cleanup before each route) -----------

let currentSession = null; // the live surface (cleanup disconnects its observer)

export function cleanup() {
  // the pane's ResizeObserver and the reprocess poll are the only
  // long-lived resources — the DOM itself is discarded by the router's
  // replaceChildren (2026-08-16: the OpenSeadragon viewer is gone; a plain
  // <img> needs no teardown)
  clearInterval(currentSession?.processingTimer);
  currentSession?.resizer?.disconnect();
  currentSession = null;
}
