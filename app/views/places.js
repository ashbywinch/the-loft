/** Places — the geography: a Leaflet/OSM heatmap over time + cards (PRD §8).
 *  Tiles need internet; without Leaflet (or if tiles fail) the SVG dot view
 *  takes over — cards and text always remain. */

import { el, header, chip, decadeList, itemCard } from "../ui.js";
import { memoriesSection } from "../memories.js";
import { navigate , canGoBackInApp } from "../router.js";
import { aggregate, artifacts as artifactsOf, evidenceFor, personAtPlace, refDateFor, reflectionsFor, sortedCounts, windowFromQuery } from "../connections.js";
import { yearOf } from "../date.js";
import { catalogued, published } from "../data.js";

const ROUTE = ["pl-aldgate", "pl-farndale-wharf", "pl-tynefield"];
const WINDOW = 2; // ± years around the slider
const UK_VIEW = { lat: 53.0, lng: -1.2, zoom: 5 };
const OSM_ATTR = "&copy; OpenStreetMap contributors";
const DEFAULT_HINT = "Tap a glowing place to explore it — the window you’ve scrubbed to travels with you.";
// Scale-aware markers (requirement, 2026-08-03): below DOTS_MIN_ZOOM the heat
// map stands alone — a red dot at country zoom is a meaningless pixel and its
// label a blob, and both obscure the heat layer. Dots become useful once
// places separate at regional zoom; labels only where they cannot collide.
// A lone active place always gets its dot and label — that is the helpful case.
const DOTS_MIN_ZOOM = 8;
const LABELS_MIN_ZOOM = 12;
const OVERVIEW_HINT = "Zoom in to mark places on the map — the cards below list what’s here.";
// Heat tuning per zoom (requirement, 2026-08-03): the default heat (blur 30,
// minOpacity 0.05, hidden above zoom 10) rendered a single point like Chenzou
// as an invisible smudge — the map must show where you can explore from the
// first paint. World scale: tight radius + high minOpacity so every place is
// a distinct vivid spot (the heat IS the marker). Street scale: smooth
// backdrop while dots and labels carry the precision.
// The colour gradient stays the plugin default (blue → red) on purpose:
// users have seen heat maps before and associate the colours — blue = few,
// red = many (user, 2026-08-03).
const HEAT_STEPS = [
  { maxZoom: 6, radius: 16, blur: 8, minOpacity: 0.55 }, // world — discrete spots
  { maxZoom: 10, radius: 26, blur: 15, minOpacity: 0.4 }, // regional — splitting blobs
  { maxZoom: 18, radius: 42, blur: 30, minOpacity: 0.22 }, // street — smooth backdrop
];

/** Which heat tuning applies at this zoom — pure, unit-tested. */
export function heatStepForZoom(zoom) {
  return HEAT_STEPS.find((s) => zoom < s.maxZoom) ?? HEAT_STEPS[HEAT_STEPS.length - 1];
}

/** What the map shows at this zoom: heat only, dots, dots+labels, or a
 *  lone active place always dot+label — pure, unit-tested (2026-08-03). */
export function scaleState(zoom, activeCount) {
  const solo = activeCount === 1;
  return {
    showDots: solo || zoom >= DOTS_MIN_ZOOM,
    showLabels: solo || zoom >= LABELS_MIN_ZOOM,
  };
}

let currentMap = null;

/** Destroy any live Leaflet map — called by the router before each view render,
 *  so leaving Places never leaks the map, its handlers, or its tile requests. */
export function cleanup() {
  if (currentMap) {
    currentMap.remove();
    currentMap = null;
  }
}

const RING_PRECISIONS = new Set(["street", "town", "county", "region"]);
const WIDE_PRECISIONS = new Set(["country", "continent"]);

/** How a place's coordinate precision scales its marker: unset/exact is a
 *  pin; a place known to a street/square draws a small uncertainty ring; a
 *  town/county/region a larger one; a country/continent mention a wide ring
 *  — the point is never presented as more precise than it is (2026-08-05). */
export function markerScale(precision) {
  if (WIDE_PRECISIONS.has(precision)) return { ring: 4, cls: "map-ring map-ring-wide" };
  if (precision === "street") return { ring: 1.6, cls: "map-ring" };
  if (RING_PRECISIONS.has(precision)) return { ring: 2.2, cls: "map-ring" };
  return { ring: 1, cls: "" };
}

/** The offline-friendly SVG dot view (also the tile-failure fallback). */
export function buildFallbackMap(places, counts, windowParams = "") {
  const max = Math.max(1, ...counts.values());
  // A place without a position has nothing to draw — Rule O nulls unverified
  // coordinates, and `translate(null, null)` is invalid SVG that would kill
  // the whole door. Skip them everywhere: dots, route, labels.
  const positioned = places.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  const line = el("path", {
    class: "map-route",
    // Filter to places that exist: a missing route place must not leave the
    // path starting with 'L' (invalid SVG data) or a stray empty segment.
    d: ROUTE.map((id) => positioned.find((p) => p.id === id))
      .filter(Boolean)
      .map((place, i) => `${i === 0 ? "M" : "L"}${place.x} ${place.y}`)
      .join(" "),
  });
  const dots = positioned.map((place) => {
    const count = counts.get(place.id) ?? 0;
    const scale = markerScale(place.precision);
    const dot = el("g", { transform: `translate(${place.x}, ${place.y})` }, [
      el("circle", {
        r: scale.ring * (2 + 6 * (count / max)),
        class: [`map-pin`, count > 0 ? "" : "dim", scale.cls].filter(Boolean).join(" ") || "map-pin",
      }),
      el("title", {}, `${place.name}: ${count}`),
      el("text", { x: 4, y: -5, class: "map-label" }, place.name),
    ]);
    return count > 0 ? el("svg:a", { class: "map-dot-link", href: `#/place/${place.id}${windowParams}` }, [dot]) : dot;
  });
  return el("svg", { class: "map", viewBox: "0 0 100 100", "aria-label": "Map of the family places" }, [line, ...dots]);
}

function mapSection(places, state, gridEl) {
  // The map can only show places with a position — Rule O nulls unverified
  // coordinates, and a heat point / marker / fitBounds on null lat/lng throws.
  // The cards grid below keeps every place (a coordinate-less place is still
  // explorable). One rule at the seam; the fallback re-guards on x/y.
  const positioned = places.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng));
  // Range derives from the data — no hardcoded floor, so pre-1960 items in
  // the real archive still appear on the map (review: silent exclusion).
  const years = published(state.items)
    .map((item) => yearOf(item))
    .filter((y) => Number.isFinite(y));
  const minYear = years.length > 0 ? Math.min(...years) : 1960;
  const maxYear = years.length > 0 ? Math.max(...years) : 1960;
  // First visit: the whole archive at once — full date range, every place.
  // The first live draw fits the map to the positioned places (regional,
  // never street) so the pins are there from the start — two walks reported
  // "the map showed me nothing until I zoomed in" (2026-08-06). Any slider
  // move engages the ±WINDOW window; person chips filter within the current
  // scope. Future (recorded, not built): explicit all-places / date-range /
  // person-subset modes, and remembering where a returning user was looking
  // last.
  let cursor = years.length ? Math.round((minYear + maxYear) / 2) : maxYear;
  let fresh = true;
  let person = "all";
  let tilesFailed = false;

  const container = el("div", { class: "map-leaflet" });
  const label = el("div", { class: "map-window" }, "");
  const slider = el("input", {
    class: "map-slider",
    type: "range",
    min: minYear,
    max: maxYear,
    value: cursor,
    "aria-label": "Timeline slider for the map",
  });
  // Only people who can actually appear on the map — an item with places —
  // get a chip; a person whose items are all placeless (e.g. a testimony)
  // would filter the map to nothing (requirement, 2026-08-03).
  // malformed dates are skipped in every view, and the ±WINDOW window applies
  // once the user scrubs — the ONE time predicate for counts, chips and the
  // grid, so a chip can never map to an empty map (reviews, 2026-08-03)
  const inWindow = (item) => {
    const y = yearOf(item);
    return Number.isFinite(y) && (fresh || (y >= cursor - WINDOW && y <= cursor + WINDOW));
  };

  const chips = el("div", { class: "chips" }, []);

  // Per-place totals over the whole archive: heat intensity and marker radii
  // are normalized against these, not the current window, so scrubbing between
  // a quiet year and a busy one keeps intensities comparable (a window-local
  // max made a single-item window always 1.0 — uniformly hot).
  const placeTotals = new Map(places.map((place) => [place.id, 0]));
  for (const item of published(state.items)) {
    for (const place of item.places ?? []) {
      if (placeTotals.has(place.id)) placeTotals.set(place.id, placeTotals.get(place.id) + 1);
    }
  }
  const globalMax = Math.max(1, ...placeTotals.values());

  const countsFor = () => {
    const counts = new Map(places.map((place) => [place.id, 0]));
    for (const item of published(state.items)) {
      if (!inWindow(item)) continue;
      for (const place of item.places ?? []) {
        // a person's map = the places they are AT (personAtPlace): the
        // explicit per-place people list is the only attestation — the
        // recipient of a letter is not at its places, and a co-mention in a
        // multi-place item links nobody anywhere (2026-08-05)
        if (person !== "all" && !personAtPlace(person, place)) continue;
        if (counts.has(place.id)) counts.set(place.id, counts.get(place.id) + 1);
      }
    }
    return counts;
  };

  const usingLeaflet = () => typeof window !== "undefined" && !!window.L?.map && !!window.L?.heatLayer && !tilesFailed;

  let map = null;
  let heatLayer = null;
  let circleLayer = null;
  let tileErrors = 0; // section-scoped: the fallback can be retried on a later gesture
  let mapGeneration = 0; // bumped on every (re)init/teardown — stale layer events must not touch a newer map
  let currentCounts = null; // last draw()'s counts — for the solo-place label rule in applyScale
  const markersByPlace = new Map(); // live markers by place id — reused across slider ticks

  const fitTo = (points, animate) => {
    if (!map || points.length === 0) return;
    // maxZoom keeps a single-place window at regional level, never street close-up
    map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lng])), { padding: [30, 30], animate, maxZoom: 10 });
  };

  const windowParams = () => {
    const base = fresh ? `from=${minYear}&to=${maxYear}` : `from=${cursor - WINDOW}&to=${cursor + WINDOW}`;
    return person === "all" ? `?${base}` : `?${base}&person=${person}`;
  };
  const openPlace = (place) => navigate(`place/${place.id}${windowParams()}`);

  // Scale-aware marker display — run on every zoom change and after every
  // draw: heat only below DOTS_MIN_ZOOM; dots from regional zoom; labels only
  // from street zoom; a single active place always shows both (2026-08-03).
  const activePlaceCount = () => (currentCounts ? [...currentCounts.values()].filter((c) => c > 0).length : 0);
  const applyScale = () => {
    if (!map || currentMap !== map) return;
    const { showDots, showLabels } = scaleState(map.getZoom(), activePlaceCount());
    for (const [, marker] of markersByPlace) {
      if (showDots) {
        if (!circleLayer.hasLayer(marker)) circleLayer.addLayer(marker);
        if (showLabels) marker.openTooltip();
        else marker.closeTooltip();
      } else {
        marker.closeTooltip();
        circleLayer.removeLayer(marker);
      }
    }
    hint.textContent = showDots ? DEFAULT_HINT : OVERVIEW_HINT;
  };

  // The heat layer re-tunes with zoom: discrete vivid spots at world scale,
  // smooth backdrop at street scale (2026-08-03). Called on zoomend and after
  // fitTo — the canvas re-renders via setOptions → redraw.
  const applyHeatForZoom = () => {
    if (!map || currentMap !== map) return;
    const step = heatStepForZoom(map.getZoom());
    heatLayer.setOptions({ radius: step.radius, blur: step.blur, minOpacity: step.minOpacity });
  };

  const draw = (animate = false) => {
    const counts = countsFor();
    currentCounts = counts;
    const points = positioned
      .filter((p) => (counts.get(p.id) ?? 0) > 0)
      .map((p) => [p.lat, p.lng, 0.2 + 0.8 * (counts.get(p.id) / globalMax)]);
    const scope = person === "all" ? "everyone" : (state.people.find((p) => p.id === person)?.name ?? person);
    label.textContent = fresh ? `${minYear}–${maxYear} · ${scope}` : `${cursor - WINDOW}–${cursor + WINDOW} · ${scope}`;
    renderGrid(counts);

    if (map && currentMap === map) {
      // identity: a stale draw() must never touch a newer live map
      heatLayer.setLatLngs(points);
      for (const place of positioned) {
        const count = counts.get(place.id) ?? 0;
        const marker = markersByPlace.get(place.id);
        if (count === 0) {
          if (marker) {
            circleLayer.removeLayer(marker);
            markersByPlace.delete(place.id);
          }
          continue;
        }
        const radius = 6 + 18 * (count / globalMax);
        const scale = markerScale(place.precision);
        const link = el("a", { href: `#/place/${place.id}${windowParams()}` }, `${place.name}: ${count}`);
        if (marker) {
          // update in place — never rebuild tooltips/markers on a slider tick
          marker.setRadius(scale.ring * radius);
          const tip = marker.getTooltip();
          const current = tip && tip.getContent();
          if (current instanceof HTMLAnchorElement) {
            // reuse the tooltip anchor — setTooltipContent would tear down and
            // re-append the tooltip DOM on every input event
            current.textContent = `${place.name}: ${count}`;
            current.setAttribute("href", `#/place/${place.id}${windowParams()}`);
          } else {
            marker.setTooltipContent(link);
          }
        } else {
          const created = L.circleMarker([place.lat, place.lng], {
            radius: scale.ring * radius,
            color: "#8a4a2f",
            weight: 1,
            fillColor: "#b4552d",
            fillOpacity: scale.ring > 1 ? 0.25 : 0.55,
            className: `map-marker ${scale.cls}`.trim(),
          })
            .bindTooltip(link, { permanent: true, direction: "top", offset: [0, -4], interactive: true })
            .on("click", () => openPlace(place))
            .addTo(circleLayer);
          markersByPlace.set(place.id, created);
        }
      }
      // Fit to the settlement pins — the places you can open. Country and
      // continent centroids (Chenzou, Ruzia, Anzoria) span the whole world and
      // pinned every first visit at zoom 1 with no pins visible — the
      // walkers' "the map showed me nothing until I zoomed in" (2026-08-06).
      // The wide places stay on the heat at the map's edge, reachable by
      // zooming out.
      const pins = positioned.filter((p) => counts.get(p.id) > 0 && !WIDE_PRECISIONS.has(p.precision));
      fitTo(
        pins.map(({ lat, lng }) => ({ lat, lng })),
        animate,
      );
      applyScale(); // settle dots/labels for the zoom fitTo landed on
      applyHeatForZoom(); // and the heat's radius/blur for that zoom
      return;
    }
    container.replaceChildren(buildFallbackMap(positioned, counts, windowParams()));
  };

  // The place list under the map follows the same filter as the map — only
  // places with activity in the current scope (2026-08-03).
  const renderGrid = (counts) => {
    const visible = places
      .filter((p) => (counts.get(p.id) ?? 0) > 0)
      .sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0));
    gridEl.replaceChildren(
      ...(visible.length
        ? visible.map((place) =>
            el("a", { class: "card place-card", href: `#/place/${place.id}${windowParams()}` }, [
              el("div", { class: "card-title" }, place.name),
              el("div", { class: "card-meta" }, `${counts.get(place.id)} item${counts.get(place.id) === 1 ? "" : "s"}`),
              el("p", { class: "story" }, place.note),
            ]),
          )
        : [el("p", { class: "empty" }, "No places in this view — scrub the slider or pick a person.")]),
    );
  };

  const hint = el("p", { class: "map-hint" }, DEFAULT_HINT);

  const drawChips = () => {
    // a chip only for people who are AT some place via an item in the current
    // window — same predicate as countsFor, recomputed on every scrub so a chip
    // never maps to an empty map (reviews, 2026-08-03)
    const visible = state.people.filter((p) =>
      published(state.items).some(
        (item) => inWindow(item) && (item.places ?? []).some((pl) => personAtPlace(p.id, pl)),
      ),
    );
    // if the active person dropped out of the window's chip set, reset to
    // Everyone — never a silently-applied filter with no visible chip
    // (review, 2026-08-03)
    if (person !== "all" && !visible.some((p) => p.id === person)) person = "all";
    const option = (id, name) =>
      el(
        "a",
        {
          class: `chip ${person === id ? "active" : ""}`,
          onclick: () => {
            person = id;
            drawChips();
            draw();
          },
        },
        name,
      );
    chips.replaceChildren(option("all", "Everyone"), ...visible.map((p) => option(p.id, p.name)));
  };

  const init = () => {
    if (!usingLeaflet() || map) return;
    const gen = ++mapGeneration; // this map's generation — stale layer events bail on mismatch
    try {
      container.replaceChildren(); // clear the pre-init SVG fallback
      map = L.map(container).setView([UK_VIEW.lat, UK_VIEW.lng], UK_VIEW.zoom);
      const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: OSM_ATTR,
        maxZoom: 18,
      }).addTo(map);
      heatLayer = L.heatLayer([], {
        radius: HEAT_STEPS[0].radius,
        blur: HEAT_STEPS[0].blur,
        minOpacity: HEAT_STEPS[0].minOpacity,
        maxZoom: 18, // gradient: plugin default
      }).addTo(map);
      circleLayer = L.layerGroup().addTo(map);
      // user zoom changes marker/label visibility and the heat's tuning
      map.on("zoomend", () => {
        applyScale();
        applyHeatForZoom();
      });
      currentMap = map;
      hint.textContent = DEFAULT_HINT; // a retried map is live again — clear the fallback message
      // tileerror fires on the TileLayer, not the map; a single transient
      // error isn't an outage — fall back to the dot view after repeated
      // failures. tileload resets the counter: two errors with a healthy
      // load between them are hiccups; two in a row (no recovery) is an outage.
      tiles.on("tileload", () => {
        if (gen !== mapGeneration) return;
        tileErrors = 0;
      });
      tiles.on("tileerror", () => {
        if (gen !== mapGeneration) return; // a torn-down layer's abort events are stale
        tileErrors += 1;
        if (tileErrors < 2) return;
        tilesFailed = true;
        // !map: after the fallback has run both map and currentMap are null,
        // and an identity check alone would then call remove() on null.
        // currentMap !== map: a stale error from a previous visit must not
        // remove a newer live map (Leaflet throws "container is being reused").
        if (!map || currentMap !== map) return;
        // Two-tier failure (docs/coding-standards.md): log the cause and tell
        // the visitor the view changed — never swap the map silently.
        console.error("places: repeated tile errors — falling back to the dot view");
        hint.textContent = "Map tiles unavailable — showing the offline dot view.";
        mapGeneration += 1; // in-flight aborts from this layer must not count against the retry
        markersByPlace.clear(); // the next map starts with fresh markers
        map.remove();
        map = null;
        currentMap = null;
        draw(); // falls back to the dot view
      });
    } catch (error) {
      // Leaflet failed partway (e.g. a missing vendor file) — log it, then
      // degrade to the dot view (docs/coding-standards.md: fail fast)
      console.error("places: Leaflet init failed — falling back to the dot view", error);
      hint.textContent = "The interactive map is unavailable — showing the offline dot view.";
      tilesFailed = true;
      mapGeneration += 1; // any late events from this attempt are stale too
      markersByPlace.clear();
      if (map) map.remove();
      map = null;
      currentMap = null;
      draw();
    }
    draw();
  };

  slider.addEventListener("input", () => {
    fresh = false; // the user is exploring — engage the window
    cursor = Number(slider.value);
    drawChips(); // chips follow the window too — never a chip that maps to nothing
    draw(false); // markers + heat update per tick; no animated fit fight
  });
  slider.addEventListener("change", () => {
    if (tilesFailed && !map) {
      // One retry per user gesture — the network may have recovered since the
      // tile-error fallback (review: the fallback was a one-way door).
      tileErrors = 0;
      tilesFailed = false;
      init();
      return;
    }
    draw(true); // one animated fit on release
  });

  drawChips();
  draw(); // SVG fallback until Leaflet is initialized in-DOM

  return {
    node: el("div", { class: "map-wrap" }, [
      container,
      el("div", { class: "map-controls" }, [slider, label]),
      chips,
      hint,
    ]),
    init,
  };
}

export function render(main, _ctx, state) {
  cleanup();
  main.append(header("Places", state));
  main.append(
    el(
      "p",
      { class: "lede" },
      "Every place the artifacts mention — the map marks each one; scrub the slider to watch activity move.",
    ),
  );
  const grid = el("div", { class: "place-grid" }, []);
  const section = mapSection(state.places, state, grid);
  main.append(section.node); // container must be in the DOM before Leaflet measures it
  section.init();
  main.append(grid);
}

export function placePage(main, ctx, state) {
  const place = state.places.find((p) => p.id === ctx.arg);
  if (!place) {
    main.append(header("Places", state), el("p", { class: "empty" }, "Not found."));
    return;
  }
  const { inWindow, from, to } = windowFromQuery(ctx.query);
  const personFilter = ctx.query.get("person");
  const allItems = published(state.items).filter((item) => item.places?.some((p) => p.id === place.id));
  let items = inWindow ? allItems.filter((item) => yearOf(item) >= from && yearOf(item) <= to) : allItems;
  if (personFilter)
    items = items.filter((item) =>
      item.places.some((p) => p.id === place.id && p.people?.includes(personFilter)),
    );
  const personName = personFilter ? (state.people.find((p) => p.id === personFilter)?.name ?? personFilter) : null;
  main.append(header(place.name, state, canGoBackInApp() ? true : "Places"));
  main.append(el("p", { class: "story lede" }, place.note));

  const agg = aggregate(allItems);
  // The People row is who is attested AT this place — the union of the
  // per-place people lists on the place's items. Co-mention in an item is
  // not presence (2026-08-05): the 2001 email's 91 people are not all at
  // its 8 places.
  const peopleAt = new Map();
  for (const item of allItems) {
    for (const link of item.places ?? []) {
      if (link.id !== place.id) continue;
      for (const pid of link.people ?? []) peopleAt.set(pid, (peopleAt.get(pid) ?? 0) + 1);
    }
  }
  const personChips = sortedCounts(peopleAt).map(([id, count]) =>
    chip(`${state.people.find((p) => p.id === id)?.name ?? id} · ${count}`, `#/person/${id}`),
  );
  const themeChips = sortedCounts(agg.themes).map(([id, count]) =>
    chip(`${state.themes.find((t) => t.id === id)?.title ?? id} · ${count}`, `#/theme/${id}`),
  );
  const conn = el("section", { class: "block" }, []);
  if (personChips.length)
    conn.append(el("h3", { class: "block-title" }, "People"), el("div", { class: "chips" }, personChips));
  if (themeChips.length)
    conn.append(el("h3", { class: "block-title" }, "Stories"), el("div", { class: "chips" }, themeChips));
  if (conn.childElementCount) main.append(conn);

  if (place.id === "pl-farndale-wharf" || place.id === "pl-goldcrest") {
    main.append(
      el("div", { class: "sv-stub" }, [
        el("span", { class: "sv-label" }, "The street today"),
        el(
          "span",
          { class: "sv-note" },
          "Street view comes with the real map — public imagery only, never family content.",
        ),
      ]),
    );
  }
  // the items list is the artifacts about the place — stories render once,
  // in the Memories block below, never twice (2026-08-06: Aldgate showed
  // "5 items" where 2 were the same stories as "Memories about Aldgate").
  // Placement is by the place's involvement date when the ref attests one
  // (a long-lived document's entry about this place), else the item's own
  // date (2026-08-06).
  const artifacts = artifactsOf(items).map((it) => ({ ...it, date: refDateFor(it, "places", place) }));
  main.append(
    el("section", {}, [
      el(
        "h2",
        { class: "section-title" },
        inWindow
          ? `${artifacts.length} items from ${place.name}, ${from}–${to}${personName ? ` · ${personName}` : ""}`
          : `${artifacts.length} items from ${place.name}${personName ? ` · ${personName}` : ""}`,
      ),
      artifacts.length
        ? decadeList(artifacts, `#/timeline?place=${place.id}${personFilter ? `&person=${personFilter}` : ""}`)
        : el("p", { class: "empty" }, "Nothing in this window — scrub the map and come back."),
    ]),
  );

  // --- memories told about this place (PRD §19) — drafts never render ---
  const memories = published(state.items).filter(
    (it) => it.type === "story" && it.places?.some((p) => p.id === place.id),
  );
  main.append(
    memoriesSection(state, {
      title: `Memories about ${place.name}`,
      stories: memories,
      buttonLabel: `Add a memory of ${place.name}`,
      anchor: { kind: "place", id: place.id, name: place.name },
    }),
  );

  // --- reflections that mention this place (2026-08-06) ---
  const reflections = reflectionsFor(catalogued(state.items), place.id);
  if (reflections.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "Reflections"),
        el(
          "div",
          { class: "clarifications" },
          reflections.map((r) => {
            const by = state.people.find((p) => p.id === r.told_by);
            const told = r.recorded ? ` · told ${r.recorded}` : "";
            return el("div", { class: "clarification" }, [
              el("p", { class: "story" }, r.story),
              el("div", { class: "card-meta" }, `${by ? `Told by ${by.name}` : "Told"}${told}`),
            ]);
          }),
        ),
      ]),
    );
  }

  // --- evidence records that attest this place (2026-08-06) ---
  const evidence = evidenceFor(catalogued(state.items), place.id);
  if (evidence.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "Evidence"),
        el("div", { class: "card-grid" }, evidence.map((e) => itemCard(e))),
      ]),
    );
  }
}
