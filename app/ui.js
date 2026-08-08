import { identityElement } from "./identity.js";
import { assetUrl, typeLabel } from "./data.js";
import { dateLabel } from "./date.js";
import { decadeBands } from "./connections.js";

/**
 * UI primitives — small DOM helpers and shared components.
 * Scrapbook-warm, not archival-clean (PRD §10): rounded cards, warm paper tones.
 */

const SVG_TAGS = new Set(["svg", "g", "path", "circle", "text", "line", "rect", "title"]);

export function el(tag, attrs = {}, children = []) {
  const isSvgAnchor = tag === "svg:a";
  const node = isSvgAnchor
    ? document.createElementNS("http://www.w3.org/2000/svg", "a")
    : SVG_TAGS.has(tag)
      ? document.createElementNS("http://www.w3.org/2000/svg", tag)
      : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.setAttribute("class", value);
    else if (key === "onclick") node.addEventListener("click", value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2), value);
    } else if (key === "checked" || key === "disabled" || key === "selected") {
      // boolean form attrs are properties — setAttribute("checked", "false")
      // would leave a truthy attribute and render a checked box
      // (reviewer, 2026-08-03)
      node[key] = Boolean(value);
    } else if (value !== null && value !== undefined) {
      node.setAttribute(key, String(value));
    }
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

export function esc(text) {
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

export function header(title, state = null) {
  // the title + the identity, nothing else: the phone's system back (and
  // the browser's) walks the hash history — a bar button is redundant
  // (2026-08-06, user). The ⌂ is gone for the same reason.
  const bar = el("header", { class: "topbar" }, [el("h1", { class: "topbar-title" }, title)]);
  if (state) bar.append(identityElement(state));
  return bar;
}

export function chip(text, href = null) {
  // A real anchor when it has an href: focusable, keyboard-activatable,
  // exposed to screen readers (WCAG AA) — a plain span otherwise.
  if (href) return el("a", { class: "chip", href }, text);
  return el("span", { class: "chip" }, text);
}

export function sectionTitle(text) {
  return el("h2", { class: "section-title" }, text);
}

export function itemCard(item, subtitle = null) {
  const first = item.assets?.[0];
  // a told memory is stamped as such — its events date and its telling date
  // both appear, so it never reads as a scanned document (user, 2026-08-03)
  const told =
    item.type === "story" && item.recorded
      ? ` · told ${dateLabel({ date: item.recorded, date_precision: "exact" })}`
      : "";
  return el("a", { class: "card item-card", href: `#/item/${item.id}` }, [
    first
      ? el("div", { class: "card-thumb" }, [
          el("img", { src: assetUrl(item.id, first.file), alt: first.caption ?? item.title, loading: "lazy" }),
        ])
      : null,
    el("div", { class: "card-body" }, [
      el("div", { class: "card-title" }, item.title),
      el(
        "div",
        { class: "card-meta" },
        `${dateLabel(item)} · ${typeLabel(item.type)}${told}${subtitle ? ` · ${subtitle}` : ""}`,
      ),
      // the description is what tells a letter apart from the rest of its
      // correspondence — it renders on the cards, truncated, and in full on
      // the item page (2026-08-05)
      item.description ? el("p", { class: "card-desc" }, item.description) : null,
    ]),
  ]);
}

export function emptyState(text) {
  return el("div", { class: "empty" }, text);
}

/** Items grouped into decade bands, capped at 8 cards per band, with a
 *  "see all on the timeline" path. The scale story: no raw walls of cards. */
export function decadeList(items, moreHref) {
  const bands = decadeBands(items);
  return el(
    "div",
    { class: "decades" },
    bands.map((band) => {
      const visible = band.items.slice(0, 8);
      const rest = band.items.length - visible.length;
      const more =
        rest > 0 ? el("a", { class: "band-more", href: moreHref }, `+${rest} more — see all on the timeline`) : null;
      return el("details", { class: "year", open: bands.length === 1 ? true : undefined }, [
        el("summary", { class: "year-summary" }, [
          el("span", { class: "year-number" }, `${band.decade}s`),
          el("span", { class: "year-count" }, `${band.items.length} item${band.items.length === 1 ? "" : "s"}`),
        ]),
        el("div", { class: "year-items" }, [...visible.map((item) => itemCard(item)), more]),
      ]);
    }),
  );
}
