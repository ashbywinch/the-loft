/**
 * The row review (docs/PLAN/row-review-ux.md) — one page, its rows in the
 * pipeline's own colours, and the reviewer's yellow lines over them. The
 * screen has one job (user): correct the guessed lines by drawing your own.
 *
 * The tints are NOT computed here: the drafts payload carries `tints[page]`
 * — `RowTint` records (a colour and the rectangles that colour fills) built
 * by the pipeline's classes — and each row is painted as one SVG path with
 * the record's fill and alpha. Every stroke change goes to the server as the
 * whole normalised set; the answer carries the corrected rows' tints, so the
 * redraw is whatever `Rows.adjust` decided (an edit of the draft: the
 * stroke's row is the row it crossed, every other row unchanged).
 *
 * One finger draws (no mode, no toolbar); two fingers pinch and pan; a tap
 * within a finger's reach of a drawn line removes it. The finish is the only
 * control: it records the page's check and opens the next page whose rows
 * still wait.
 */

import { el, header } from "../ui.js";
import { navigate } from "../router.js";
import { rowAdjustmentBody, strokeAt, strokesFromAdjustments, widthFitRect } from "./review.js";

const ROW_STROKE_MIN = 24; // page px of travel below which a touch is a tap, not a line
const TAP_SCREEN_PX = 26; // a tap within this of a drawn line removes it

/** One row's tint as an SVG path: its rectangles as subpaths, filled once at
 *  the record's alpha — the pipeline's single composite. */
export function tintPath(rects) {
  return (rects || []).map((r) => `M${r.x0} ${r.y0}H${r.x1}V${r.y1}H${r.x0}Z`).join("");
}

/** The tints → the row layer's paths. The fill and the opacity come from the
 *  record, never from a colour rule here. */
export function paintTints(group, tints) {
  group.replaceChildren(
    ...(tints || []).map((tint) => {
      const [red, green, blue, alpha] = tint.colour;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", tintPath(tint.rects));
      path.setAttribute("fill", `rgb(${red} ${green} ${blue})`);
      path.setAttribute("fill-opacity", String(alpha / 255));
      return path;
    }),
  );
}

/** The rect the view fits: the writing's own union (the rows' rectangles),
 *  so the whole row set is on screen at a drawable pitch. */
export function rowsRect(tints) {
  const rects = (tints || []).flatMap((tint) => tint.rects || []);
  if (!rects.length) return null;
  const x0 = Math.min(...rects.map((r) => r.x0));
  const y0 = Math.min(...rects.map((r) => r.y0));
  const x1 = Math.max(...rects.map((r) => r.x1));
  const y1 = Math.max(...rects.map((r) => r.y1));
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

/** A stroke's path length — how the screen tells a line from a tap. */
export function strokeLength(stroke) {
  return (stroke || []).reduce(
    (sum, point, i) => (i ? sum + Math.hypot(point.x - stroke[i - 1].x, point.y - stroke[i - 1].y) : 0),
    0,
  );
}

function paintStrokes(svg, strokes, live) {
  svg.replaceChildren();
  const lines = live ? [...strokes, live] : strokes;
  for (const points of lines) {
    if (points.length < 2) continue;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("class", `rv-stroke${points === live ? " rv-stroke--live" : ""}`);
    line.setAttribute("points", points.map((p) => `${p.x},${p.y}`).join(" "));
    svg.append(line);
  }
}

async function loadDrafts(batchId, docIndex, pageIndex) {
  try {
    // one page's maps, not the whole batch: the row screen renders exactly
    // this page, and the whole-batch payload is the 12-second client cost
    const query = `?doc=${docIndex}&page=${pageIndex}`;
    const res = await fetch(`/api/sync/batch/${encodeURIComponent(batchId)}/drafts${query}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("rows: the drafts could not be loaded", error);
    return null;
  }
}

async function postRows(batchId, page, strokes, imgSize) {
  try {
    const res = await fetch(
      `/api/sync/batch/${encodeURIComponent(batchId)}/page/${encodeURIComponent(page)}/row-adjustments`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(rowAdjustmentBody(strokes, imgSize)),
      },
    );
    const payload = await res.json();
    if (!res.ok) throw new Error(payload?.error || `the rows did not save (${res.status})`);
    return payload;
  } catch (error) {
    console.error("rows: the correction did not save", error);
    return { error: String(error?.message || error) };
  }
}

export async function render(main, ctx, state) {
  const batchId = ctx.arg;
  const docIndex = Number(ctx.rest?.[2]);
  const pageIndex = Number(ctx.rest?.[3]);
  // The drafts read the batch's work files; a slow disk or link must show
  // progress, never an empty page.
  main.replaceChildren(header("Rows", state, "Review"), el("p", { class: "empty" }, "Loading the page…"));
  const drafts = await loadDrafts(batchId, docIndex, pageIndex);
  const doc = drafts?.documents?.[0];
  const page = doc?.pages?.[pageIndex];
  if (!doc || !page) {
    main.replaceChildren(
      header("Rows", state, "Review"),
      el("p", { class: "empty" }, "That page is not in this batch."),
    );
    return;
  }

  const tints = doc.tints?.[page] || [];
  const checked = new Set(Object.keys(doc.adjusted_rows || {}));
  const root = el("div", { class: "rv rv-rows" });
  const bar = el("button", { class: "rv-btn rv-btn--primary", type: "button" }, "Rows are right");
  root.append(
    el("div", { class: "rv-topbar" }, [
      el("button", { class: "rv-back", type: "button", onclick: () => navigate("#/review") }, "← Review"),
      el("div", { class: "rv-topbar-titles" }, [el("div", { class: "rv-tt" }, "Rows")]),
    ]),
    el("div", { class: "rv-imgpane" }, [el("div", { class: "rv-imgbox" })]),
    el("footer", { class: "rv-rowbar" }, [bar]),
  );
  main.replaceChildren(root);

  const imgBox = root.querySelector(".rv-imgbox");
  const layer = el("div", { class: "rv-layer" });
  const img = el("img", { class: "rv-page", alt: "" });
  const tintsSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  tintsSvg.setAttribute("class", "rv-tints");
  const tintGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
  tintGroup.setAttribute("class", "rv-tint");
  const drawSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  drawSvg.setAttribute("class", "rv-draw");
  tintsSvg.append(tintGroup);
  layer.append(img, tintsSvg, drawSvg);
  const imageNote = el("div", { class: "rv-note" }, "Loading the page image…");
  imgBox.append(layer, imageNote);
  if (!tints.length) {
    imgBox.append(el("div", { class: "rv-note" }, "No word boxes to correct on this page — re-read it first."));
    bar.disabled = true;
  }
  paintTints(tintGroup, tints);

  const session = { view: null, strokes: [], live: null, imgSize: null, dirty: false };
  const paneScale = () => imgBox.clientWidth / Math.max(session.view.width, 1);
  const clampView = (view) => {
    const { w, h } = session.imgSize;
    return {
      ...view,
      x: Math.max(0, Math.min(w - view.width, view.x)),
      y: Math.max(0, Math.min(h - view.height, view.y)),
    };
  };
  const renderView = () => {
    if (!session.view || !session.imgSize) return;
    const scale = imgBox.clientWidth / session.view.width;
    layer.style.setProperty("--rv-inv", String(1 / scale)); // 11 screen px at any zoom
    layer.style.transform = `translate(${-session.view.x * scale}px, ${-session.view.y * scale}px) scale(${scale})`;
  };
  const pagePoint = (clientX, clientY) => {
    const rect = imgBox.getBoundingClientRect();
    const scale = paneScale();
    return {
      x: session.view.x + (clientX - rect.left) / scale,
      y: session.view.y + (clientY - rect.top) / scale,
    };
  };
  const redrawStrokes = () => paintStrokes(drawSvg, session.strokes, session.live);

  img.onload = () => {
    imageNote.remove();
    session.imgSize = { w: img.naturalWidth, h: img.naturalHeight };
    layer.style.width = `${session.imgSize.w}px`;
    layer.style.height = `${session.imgSize.h}px`;
    for (const svg of [tintsSvg, drawSvg]) {
      svg.setAttribute("viewBox", `0 0 ${session.imgSize.w} ${session.imgSize.h}`);
    }
    session.strokes = strokesFromAdjustments(doc.row_adjustments?.[page], session.imgSize);
    redrawStrokes();
    const rect = rowsRect(tints) || { x: 0, y: 0, width: session.imgSize.w, height: session.imgSize.h };
    const pad = Math.max(24, rect.height * 0.04);
    session.view = clampView(
      widthFitRect(imgBox.clientWidth, imgBox.clientHeight, {
        x: Math.max(0, rect.x - pad),
        y: Math.max(0, rect.y - pad),
        width: Math.min(session.imgSize.w, rect.width + pad * 2),
        height: Math.min(session.imgSize.h, rect.height + pad * 2),
      }),
    );
    renderView();
  };
  img.onerror = () => {
    imageNote.remove();
    layer.remove();
    imgBox.append(el("div", { class: "rv-note" }, "Could not load the page image."));
  };
  img.src = `/api/sync/batch/${encodeURIComponent(batchId)}/page/${encodeURIComponent(page)}`;

  const submit = async () => {
    const answer = await postRows(batchId, page, session.strokes, session.imgSize);
    if (answer?.tints) {
      paintTints(tintGroup, answer.tints);
      session.dirty = false;
      bar.textContent = answer.violations?.length ? answer.violations[0] : "Rows are right";
      checked.add(page);
    } else {
      bar.textContent = "Could not save — try again";
    }
    return answer;
  };

  // ---- the gestures: one finger draws, a tap removes, two pinch and pan ----
  const pointers = new Map();
  let pinch = null;
  const commit = async (stroke) => {
    if (strokeLength(stroke) < ROW_STROKE_MIN) {
      const at = strokeAt(session.strokes, stroke[0], TAP_SCREEN_PX / paneScale());
      if (at === null) return;
      session.strokes.splice(at, 1);
    } else {
      session.strokes.push(stroke);
    }
    session.dirty = true;
    redrawStrokes();
    await submit();
  };
  const onMove = (event) => {
    if (!pointers.has(event.pointerId) || !session.view) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (session.live && pointers.size === 1) {
      const point = pagePoint(event.clientX, event.clientY);
      const last = session.live.at(-1);
      if (Math.hypot(point.x - last.x, point.y - last.y) >= 3) {
        session.live.push(point);
        redrawStrokes();
      }
      return;
    }
    if (pointers.size === 2 && pinch) {
      const [a, b] = [...pointers.values()];
      const rect = imgBox.getBoundingClientRect();
      const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const mid = { x: (a.x + b.x) / 2 - rect.left, y: (a.y + b.y) / 2 - rect.top };
      const width = clampView({ ...pinch.view, width: pinch.view.width / (dist / pinch.dist) }).width;
      const height = (width * imgBox.clientHeight) / Math.max(imgBox.clientWidth, 1);
      const scale = imgBox.clientWidth / pinch.view.width;
      const anchor = { x: pinch.view.x + pinch.mid.x / scale, y: pinch.view.y + pinch.mid.y / scale };
      session.view = clampView({
        width,
        height,
        x: anchor.x - (mid.x * width) / imgBox.clientWidth,
        y: anchor.y - (mid.y * height) / imgBox.clientHeight,
      });
      renderView();
    }
  };
  const onUp = async (event) => {
    const stroke = pointers.size === 1 ? session.live : null;
    session.live = null;
    pointers.delete(event.pointerId);
    if (pointers.size) pinch = null;
    if (stroke) {
      redrawStrokes();
      await commit(stroke);
    }
    if (!pointers.size) {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    }
  };
  imgBox.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (!session.view) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 1) {
      // one finger draws: the page IS the tool (no mode, no button)
      session.live = [pagePoint(event.clientX, event.clientY)];
      pinch = null;
      bar.textContent = "Rows are right";
    } else if (pointers.size === 2) {
      // a second finger is a pinch or a pan, never a stroke
      session.live = null;
      const [a, b] = [...pointers.values()];
      const rect = imgBox.getBoundingClientRect();
      pinch = {
        dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
        view: { ...session.view },
        mid: { x: (a.x + b.x) / 2 - rect.left, y: (a.y + b.y) / 2 - rect.top },
      };
    }
    redrawStrokes();
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  });

  bar.addEventListener("click", async () => {
    bar.disabled = true;
    if (session.dirty) {
      const answer = await submit();
      if (answer?.error) {
        bar.disabled = false;
        return;
      }
    }
    // the next page whose rows still wait; the hub when none does
    const pages = doc.pages || [];
    const next = pages.findIndex((name, index) => index > pageIndex && !checked.has(name));
    navigate(next >= 0 ? `#/rows/${batchId}/${docIndex}/${next}` : "#/review");
  });
}
