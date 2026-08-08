/** Timeline — the spine: years with density, filters, and the enumeration
 *  home for entity pages (?person=, ?place=) at scale (PRD §8). */

import { el, header, itemCard, emptyState, sectionTitle } from "../ui.js";
import { itemInvolves } from "../connections.js";
import { itemDateFor } from "../connections.js";
import { ageInYears, dateLabel, yearOf } from "../date.js";
import { published } from "../data.js";

const FILTERS = [
  ["all", "Everything"],
  ["letter", "Letters"],
  ["photo", "Photos"],
  ["object", "Objects"],
  ["story", "Stories"],
  ["event", "Events"],
];

/** The distinguishing detail for a person on the spine — the first dated
 *  spouse's name ("married Clara Kendall"), else occupation, else an
 *  alias. Same-name people must not be four identical entries (2026-08-06):
 *  the 1828 and 1892 Walter Kendalls are told apart by who they married.
 *  Unknown-named spouses ("? Corbett") never carry the label. */
function personDetail(p, rels, people) {
  const byId = new Map(people.map((x) => [x.id, x]));
  const spouses = rels
    .filter((r) => r.kind === "spouse" && (r.a === p.id || r.b === p.id))
    .map((r) => ({ other: byId.get(r.a === p.id ? r.b : r.a), dated: Boolean(r.date) }))
    .filter((s) => s.other && !s.other.name.startsWith("?"));
  spouses.sort((a, b) => Number(b.dated) - Number(a.dated)); // stable: attested-dated first
  if (spouses.length) return `married ${spouses[0].other.name}`;
  if (p.occupations?.length) return p.occupations[0];
  if (p.aliases?.length) return `known as ${p.aliases[0]}`;
  return null;
}

/** The attested life events the timeline derives from the identity tables:
 *  a person's dob is a birth, dod a death, and a dated spouse edge is a
 *  marriage. These are facts in the archive, arranged by date — never
 *  invented here (PRD §10). Stored event items (type "event", an attested
 *  happening like a concert a letter mentions) flow through the item path. */
export function lifeEvents(people, relationships) {
  const events = [];
  const brief = (p) => ({ id: p.id, name: p.name });
  const POINT = new Set(["exact", "month", "year", "approx"]);
  const push = (ev) => events.push({ derived: true, ...ev });
  for (const person of people) {
    // unconfirmed facts never render on the spine — a proposed person's
    // dob/dod is a proposal, not a happening (2026-08-06, §10 propose/confirm)
    if (person.status === "proposed") continue;
    // only point precisions place an event on the spine — "died after 1917"
    // is not a 1917 happening (2026-08-06, the recognition principle); the
    // fact stays on the person page
    if (person.dob && POINT.has(person.dob.precision)) {
      const detail = personDetail(person, relationships ?? [], people);
      push({ date: person.dob.date, precision: person.dob.precision, kind: "birth", people: [detail ? { ...brief(person), detail } : brief(person)] });
    }
    if (person.dod && POINT.has(person.dod.precision)) {
      const detail = personDetail(person, relationships ?? [], people);
      push({ date: person.dod.date, precision: person.dod.precision, kind: "death", people: [detail ? { ...brief(person), detail } : brief(person)] });
    }
  }
  for (const rel of relationships ?? []) {
    if (rel.kind !== "spouse" || !rel.date || !POINT.has(rel.date.precision)) continue;
    const a = people.find((p) => p.id === rel.a);
    const b = people.find((p) => p.id === rel.b);
    if (!a || !b) continue;
    const marriage = { date: rel.date.date, precision: rel.date.precision, kind: "marriage", people: [brief(a), brief(b)] };
    // the ages at marriage — calculated from the spouses' dobs, never stored
    const ages = [a, b].map((p) => ageInYears(p.dob, { date: rel.date.date, precision: rel.date.precision }));
    if (ages.every(Boolean)) marriage.ages = ages.map((x) => (x.exact ?? `${x.from}–${x.to}`));
    push(marriage);
  }
  return events;
}

/** The timeline's periods: the chronological spine packed into count-sized,
 *  year-aligned buckets — hundreds of items must not mean hundreds of bands.
 *  A bucket closes once it holds *target* entries and the next year begins;
 *  a year alone over the target is its own period (2026-08-05). */
export function bucketPeriods(entries, target = 20) {
  const byYear = new Map();
  for (const e of entries) {
    const y = yearOf(e);
    if (!Number.isFinite(y)) continue;
    if (!byYear.has(y)) byYear.set(y, []);
    byYear.get(y).push(e);
  }
  const years = [...byYear.keys()].sort((a, b) => a - b);
  const periods = [];
  let current = [];
  for (const y of years) {
    const yearEntries = byYear.get(y).sort((a, b) => a.date.localeCompare(b.date));
    if (yearEntries.length > target) {
      if (current.length) {
        periods.push(current);
        current = [];
      }
      for (let i = 0; i < yearEntries.length; i += target) periods.push(yearEntries.slice(i, i + target));
      continue;
    }
    if (current.length && current.length + yearEntries.length > target) {
      periods.push(current);
      current = [];
    }
    current.push(...yearEntries);
  }
  if (current.length) periods.push(current);
  return periods;
}

/** The period's label range: "1828" or "1868–1949". */
export function periodRange(period) {
  const years = period.map((e) => yearOf(e)).filter(Number.isFinite);
  const min = Math.min(...years);
  const max = Math.max(...years);
  return min === max ? String(min) : `${min}–${max}`;
}

/** The period's hook — the dominant theme's id when one genuinely keynotes
 *  the period's items (at least two items, and a fifth of the non-derived
 *  entries — life events carry no themes and must not dilute the share),
 *  else null. A single themed item is not "the key contents" (2026-08-05). */
export function periodHook(period) {
  const counts = new Map();
  let items = 0;
  for (const entry of period) {
    if (entry.derived) continue;
    items += 1;
    for (const t of entry.themes ?? []) counts.set(t.id, (counts.get(t.id) ?? 0) + 1);
  }
  let best = null;
  let bestCount = 0;
  for (const [id, n] of counts) if (n > bestCount) {
    best = id;
    bestCount = n;
  }
  if (!best || bestCount < 2 || items === 0 || bestCount * 5 < items) return null;
  return best;
}

const EVENT_VERBS = { birth: "born", death: "died", marriage: "married" };

/** A derived life event's card — links to the person, reads as a spine
 *  entry with its own date: "Harper Pryce · born 1 May 1828". The date is on
 *  the card, never implied by the period's range (2026-08-06). */
function eventCard(ev) {
  const verb = EVENT_VERBS[ev.kind] ?? ev.kind;
  const name = ev.people.map((p) => p.name).join(" and ");
  const when = dateLabel({ date: ev.date, date_precision: ev.precision, date2: ev.date2 });
  const ages = ev.ages?.length ? ` (aged ${ev.ages.join(" · ")})` : "";
  const detail = ev.people[0]?.detail ? ` · ${ev.people[0].detail}` : "";
  return el("a", { class: "event-card", href: `#/person/${ev.people[0].id}` }, [
    el("span", { class: "event-name" }, name),
    " ",
    el("span", { class: "event-kind" }, `· ${verb} ${when}${ages}${detail}`),
  ]);
}

export function render(main, ctx, state) {
  const filter = FILTERS.some(([key]) => key === ctx.query.get("type")) ? ctx.query.get("type") : "all";
  const personFilter = ctx.query.get("person");
  const placeFilter = ctx.query.get("place");

  let items = published(state.items);
  if (personFilter) items = items.filter((item) => itemInvolves(item, personFilter));
  if (placeFilter) items = items.filter((item) => item.places?.some((p) => p.id === placeFilter));
  if (filter !== "all") items = items.filter((item) => item.type === filter);

  // Derived life events ride with Everything and the Events filter; the
  // letter/photo/object/story filters are item-only, and an event has no
  // places to ride a place filter (2026-08-05).
  let events = lifeEvents(state.people, state.relationships ?? []);
  if (personFilter) events = events.filter((ev) => ev.people.some((p) => p.id === personFilter));
  if (filter !== "all" && filter !== "event") events = [];
  if (placeFilter) events = [];

  const person = personFilter ? state.people.find((p) => p.id === personFilter) : null;
  const place = placeFilter ? state.places.find((p) => p.id === placeFilter) : null;
  const title = person ? `Timeline — ${person.name}` : place ? `Timeline — ${place.name}` : "Timeline";
  main.append(header(title, state));

  const active = [];
  if (person) active.push(el("span", { class: "chip active" }, `${person.name} ✕`));
  if (place) active.push(el("span", { class: "chip active" }, `${place.name} ✕`));
  if (active.length) {
    main.append(el("div", { class: "chips" }, [...active, el("a", { class: "chip", href: "#/timeline" }, "Clear")]));
  }

  const filters = el(
    "div",
    { class: "chips" },
    FILTERS.map(([key, label]) =>
      el(
        "a",
        {
          class: `chip ${key === filter ? "active" : ""}`,
          href: `#/timeline?type=${key}${personFilter ? `&person=${personFilter}` : ""}${placeFilter ? `&place=${placeFilter}` : ""}`,
        },
        label,
      ),
    ),
  );

  main.append(filters);
  if (items.length === 0 && events.length === 0) {
    main.append(
      emptyState(
        filter === "photo"
          ? "No photos yet — the collection is still growing." // photos ARE supported; none have been added (2026-08-06, Eli walk)
          : "Nothing here yet — the collection is still arriving.",
      ),
    );
    return;
  }

  // Under a person filter, an item is placed by the person's involvement
  // date when the ref states one — the family record sits at 1945 on
  // Nora's timeline, not 1868 (2026-08-06). The clone carries the date
  // through the period bucketing and the card's own date label.
  const spineEntries = personFilter
    ? items.map((it) => ({ ...it, date: itemDateFor(it, person) })).concat(events)
    : [...items, ...events];
  const periods = bucketPeriods(spineEntries);
  main.append(
    sectionTitle(
      `${periods.length} period${periods.length === 1 ? "" : "s"}, ${items.length} item${items.length === 1 ? "" : "s"}${
        events.length ? ` · ${events.length} event${events.length === 1 ? "" : "s"}` : ""
      }`,
    ),
  );

  const openYear = ctx.arg ? Number(ctx.arg) : null;
  for (const period of [...periods].reverse()) {
    const hookId = periodHook(period);
    const hook = hookId ? state.themes.find((t) => t.id === hookId)?.title : null;
    const details = el("details", { class: "period" }, [
      el("summary", { class: "period-summary" }, [
        el("span", { class: "period-range" }, periodRange(period)),
        hook ? el("span", { class: "period-hook" }, `· ${hook}`) : null,
        el("span", { class: "period-count" }, `${period.length} entr${period.length === 1 ? "y" : "ies"}`),
      ]),
      el(
        "div",
        { class: "year-items" },
        [...period].reverse().map((entry) => (entry.derived ? eventCard(entry) : itemCard(entry))),
      ),
    ]);
    if (openYear !== null && period.some((e) => yearOf(e) === openYear)) details.setAttribute("open", "");
    main.append(details);
  }
}
