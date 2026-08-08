/**
 * Family tree — the person-centred view, the established mobile pattern
 * (FamilySearch's mobile tree; bondar.design's single-level relation
 * visibility; PRECEDENT.md §5). One person at the centre: parents above,
 * partner beside, siblings and children below — position encodes relationship,
 * no connector lines. Tap a card to re-centre the tree; tap the centre card
 * to open the profile. Rendered from the relationship edges in people.json
 * (TECH-SPEC §4); the view arranges them, it never invents them (PRD §10).
 */

import { el, header } from "../ui.js";
import { me } from "../data.js";

const FAMILY_KINDS = new Set(["spouse", "parent", "sibling", "inlaw"]);

/** The card's life line — "1828–1909" when both dates are point-precisions
 *  (approx reads "circa 1790–circa 1862"), else the short "b. 1828" /
 *  "d. 1909" forms. Year-granularity: a tree card must stay short enough
 *  to sit two-to-a-row on a phone — a full "b. 12 Aug 1820" wraps to three
 *  lines and stretches the row (2026-08-06, user). The person page keeps
 *  the full dates. */
function lifeLine(person) {
  const dob = person.dob;
  const dod = person.dod;
  const POINT = new Set(["exact", "month", "year", "approx"]);
  const label = (d) => (d.precision === "approx" ? `circa ${Number(d.date.slice(0, 4))}` : d.date.slice(0, 4));
  if (dob && dod && POINT.has(dob.precision) && POINT.has(dod.precision)) return `${label(dob)}–${label(dod)}`;
  if (dob && POINT.has(dob.precision)) return `b. ${label(dob)}`;
  if (dod && POINT.has(dod.precision)) return `d. ${label(dod)}`;
  return null;
}

/** The people the tree can place — those with at least one family edge. */
/** The import's unconfirmed person ids — never family until the owner
 *  confirms them (2026-08-07, user: proposed people are a pending import). */
function proposedIds(state) {
  return new Set((state.people ?? []).filter((p) => p.status === "proposed").map((p) => p.id));
}

export function familyIds(state) {
  const rels = state.relationships ?? [];
  const proposed = proposedIds(state);
  return new Set(
    state.people
      .filter((p) => !proposed.has(p.id) && rels.some((r) => (r.a === p.id || r.b === p.id) && FAMILY_KINDS.has(r.kind)))
      .map((p) => p.id),
  );
}

/** The most-connected person — the fallback first centre for the tree. */
export function defaultFocus(state, preferredId = null) {
  if (preferredId && familyIds(state).has(preferredId)) return preferredId;
  const degree = new Map();
  for (const r of state.relationships ?? []) {
    if (!FAMILY_KINDS.has(r.kind)) continue; // the tree can only place family kinds
    degree.set(r.a, (degree.get(r.a) ?? 0) + 1);
    degree.set(r.b, (degree.get(r.b) ?? 0) + 1);
  }
  let best = null;
  let bestDeg = -1;
  for (const p of state.people) {
    const d = degree.get(p.id) ?? 0;
    if (d > bestDeg) {
      best = p.id;
      bestDeg = d;
    }
  }
  return best ?? state.people[0]?.id ?? null;
}

/** The undirected family graph — the tree's placement and the path clues
 *  (2026-08-06: extracted so render() can trace the route without a second
 *  build). */
export function familyGraph(state) {
  const family = new Map();
  const proposed = proposedIds(state);
  const link = (a, b) => {
    if (!family.has(a)) family.set(a, new Set());
    family.get(a).add(b);
  };
  for (const r of state.relationships ?? []) {
    if (!FAMILY_KINDS.has(r.kind)) continue;
    if (proposed.has(r.a) || proposed.has(r.b)) continue; // unconfirmed identities are not family
    link(r.a, r.b);
    link(r.b, r.a);
  }
  return family;
}

/** The full family path from → to (BFS, first-found shortest) — the route
 *  the path bar shows, from the current focus through every family step to
 *  the narrator. Null when unreachable or already there. */
export function pathTo(family, from, to) {
  if (!to || from === to || !family.has(from)) return null;
  const prev = new Map([[from, null]]);
  const queue = [from];
  while (queue.length) {
    const cur = queue.shift();
    for (const n of family.get(cur) ?? []) {
      if (prev.has(n)) continue;
      prev.set(n, cur);
      if (n === to) {
        const path = [];
        let node = n;
        while (node !== null) {
          path.unshift(node);
          node = prev.get(node);
        }
        return path;
      }
      queue.push(n);
    }
  }
  return null;
}

/** The signed-in narrator's person id — the target of the "leads back to
 *  you" clue and the preferred first centre. Null when not signed in: the
 *  tree opens on the most-connected person and no path bar renders — the
 *  identity is the verified session, never a claimed name (2026-08-06). */
export function narratorId(state) {
  return me(state)?.person ?? null;
}

/** The tree node for a focus person: parents / centre(+partner) / siblings / children / wider. */
export function buildTree(state, focusId, opts = {}) {
  const rels = state.relationships ?? [];
  const people = new Map(state.people.map((p) => [p.id, p]));
  const person = people.get(focusId);
  if (!person) return el("p", { class: "empty" }, "Person not found.");

  // The undirected family graph — the tree's placement and the "unseen
  // links" / "leads back to you" clues (2026-08-05).
  const family = familyGraph(state);
  const proposed = proposedIds(state);

  const notProposed = (id) => !proposed.has(id);
  const parents = rels.filter((r) => r.kind === "parent" && r.b === focusId && notProposed(r.a)).map((r) => r.a);
  const children = rels.filter((r) => r.kind === "parent" && r.a === focusId && notProposed(r.b)).map((r) => r.b);
  const siblings = rels
    .filter((r) => r.kind === "sibling" && (r.a === focusId || r.b === focusId))
    .map((r) => (r.a === focusId ? r.b : r.a))
    .filter(notProposed);
  const partners = rels
    .filter((r) => r.kind === "spouse" && (r.a === focusId || r.b === focusId))
    .map((r) => (r.a === focusId ? r.b : r.a))
    .filter(notProposed);
  const wider = rels.filter(
    (r) => (r.kind === "inlaw" || r.kind === "teacher") && (r.a === focusId || r.b === focusId),
  );
  const widerIds = wider.map((r) => (r.a === focusId ? r.b : r.a)).filter(notProposed);

  // Everything this view shows — a person's family links beyond it are
  // "unseen" and the card must say so.
  const visibleIds = new Set([focusId, ...parents, ...children, ...siblings, ...partners, ...widerIds]);
  // the first hop toward the narrator — the "leads back to you" marker
  const backStep = (opts.path && opts.path.length > 1 ? opts.path[1] : null) ?? null;

  const card = (id) => {
    const p = people.get(id);
    if (!p) return null;
    const unseen = [...(family.get(id) ?? [])].filter((n) => !visibleIds.has(n)).length;
    const markers = [];
    if (unseen > 0) markers.push(el("span", { class: "tree-more" }, `+${unseen} more`));
    if (id === backStep) markers.push(el("span", { class: "tree-back" }, "leads back to you"));
    return el(
      "a",
      {
        // every card moves the tree — one action per card, never a link
        // inside a link (2026-08-06, UX walk 3): the open action lives in
        // the button the focus card grows
        class: "tree-card",
        href: `#/tree?person=${id}`,
      },
      [
        el("img", { class: "avatar", src: `data/assets/avatar-${id}.svg`, alt: p.name }),
        el("div", { class: "tree-name" }, p.name),
        ...(lifeLine(p) ? [el("div", { class: "tree-years" }, lifeLine(p))] : []),
        ...markers,
      ],
    );
  };

  const focusCard = (id) => {
    const p = people.get(id);
    if (!p) return null;
    return el("div", { class: "tree-focus" }, [
      card(id),
      // the affordance-on-selection (the map-pin / MyHeritage pattern): the
      // centred card grows its open action, so no target hides a second
      // meaning (2026-08-06, UX walks 2+3: "the centre card opens their
      // page" was learned only by trial)
      el("a", { class: "tree-open", href: `#/person/${id}` }, "Open their page"),
    ]);
  };

  const band = (title, ids) => {
    const cards = ids.map((id) => card(id)).filter(Boolean);
    if (!cards.length) return null;
    return el("div", { class: "tree-band" }, [
      el("div", { class: "tree-role" }, title),
      el("div", { class: "tree-cards" }, cards),
    ]);
  };

  const centre = el("div", { class: "tree-centre" }, [
    focusCard(focusId),
    ...partners.map((id) => card(id)).filter(Boolean),
  ]);

  const widerChips = wider.map((r) => {
    const otherId = r.a === focusId ? r.b : r.a;
    const label = (r.a === focusId ? r.label_a : r.label_b) ?? r.kind; // never "Name — undefined"
    const p = people.get(otherId);
    return el("a", { class: "tree-rel", href: `#/person/${otherId}` }, `${p?.name ?? otherId} — ${label}`);
  });

  const node = el(
    "div",
    { class: "tree-ego" },
    // drop null bands — an empty band renders as a literal "null" text node
    // (cast.js convention; review, 2026-08-03)
    [
      band("Parents", parents),
      centre,
      band("Siblings", siblings),
      band("Children", children),
      widerChips.length ? el("div", { class: "tree-rel-row" }, widerChips) : null,
    ].filter(Boolean),
  );
  return node;
}

/** The path bar — "The path to you: …" (the breadcrumb pattern from the
 *  research, 2026-08-06): each hop re-centres the tree, the narrator's name
 *  links to their record. Full trail up to five hops; beyond that the middle
 *  collapses to an ellipsis — the first and last steps carry the route. Only
 *  when the narrator is known, reachable, and not the focus. */
function pathBar(state, route) {
  const byId = new Map(state.people.map((p) => [p.id, p.name]));
  const hops = route.length - 1;
  const visible = hops > 5 ? [route[0], null, route[route.length - 2], route[route.length - 1]] : route;
  const parts = [];
  visible.forEach((id, i) => {
    if (i > 0) parts.push(el("span", { class: "tree-path-sep" }, " → "));
    if (id === null) {
      parts.push(el("span", { class: "tree-path-gap" }, "…"));
      return;
    }
    const name = byId.get(id) ?? id;
    parts.push(
      i === 0
        ? el("span", { class: "tree-path-current" }, name) // the focus: the page you're on (breadcrumb law)
        : i === visible.length - 1
          ? el("a", { class: "tree-path-you", href: `#/person/${id}` }, name)
          : el("a", { class: "tree-path-hop", href: `#/tree?person=${id}` }, name),
    );
  });
  return el("p", { class: "tree-path" }, ["The path to you: ", ...parts]);
}

export function render(main, ctx, state) {
  main.append(header("Family tree", state));
  main.append(
    el(
      "p",
      { class: "lede" },
      "Tap any card to centre the tree — Open their page reads the centred person's record.",
    ),
  );
  const requested = ctx.query.get("person");
  const focus =
    requested && state.people.some((p) => p.id === requested)
      ? requested
      : defaultFocus(state, narratorId(state));
  const narrator = narratorId(state);
  const route = pathTo(familyGraph(state), focus, narrator);
  if (route && route.length > 1) main.append(pathBar(state, route));
  main.append(buildTree(state, focus, { narratorId: narrator, path: route }));
}
