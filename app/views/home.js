/** Home — the front door: today's moment, wander, recent, the doors (PRD §8). */

import { el, header, itemCard, sectionTitle } from "../ui.js";
import { monthDayDistance, sortByRecorded } from "../date.js";
import {
  documentsToIdentify,
  documentsToReview,
  drafts,
  isMine,
  me,
  pagesToCheck,
  pendingImports,
  proposedPeople,
  published,
} from "../data.js";


function todayMoment(items) {
  const now = new Date();
  let best = null;
  let bestDelta = Infinity;
  for (const item of items) {
    // A story's moment-worthy date is the events' date, never the day it was
    // told: a story whose date equals its recorded/created stamp has no
    // distinct event date and is not an anniversary.
    if (item.type === "story") {
      const told = (item.recorded || item.created || "").slice(0, 10);
      if (told && told === item.date) continue;
    }
    const delta = monthDayDistance(item, now);
    if (delta === null) continue;
    const dist = Math.abs(delta);
    if (dist <= 4 && dist < bestDelta) {
      best = { item, delta, dist };
      bestDelta = dist;
    }
  }
  if (!best) return null;
  // The anniversary that just passed is `delta` days before today; derive the
  // elapsed years from it, not the current calendar year, so a Dec 31 item
  // read on Jan 1 keeps its correct year.
  const anniversary = new Date(now.getFullYear(), now.getMonth(), now.getDate() + best.delta);
  const years = anniversary.getFullYear() - Number.parseInt(best.item.date.slice(0, 4), 10);
  // An anniversary requires a past year: an item dated this year (a story
  // told this week) is not history — "0 years ago this week" is a lie, and a
  // fresh testimony is not a memory card.
  if (years < 1) return null;
  const when =
    best.delta === 0
      ? "On this day"
      : best.delta < 0
        ? `${years} year${years === 1 ? "" : "s"} ago this week`
        : `Upcoming anniversary — in ${best.delta} day${best.delta === 1 ? "" : "s"}`;
  return el("a", { class: "moment", href: `#/item/${best.item.id}` }, [
    el("span", { class: "moment-when" }, when),
    el("span", { class: "moment-title" }, best.item.title),
    el("span", { class: "moment-note" }, "From the letters — open it, wander a little further."),
  ]);
}

export function render(main, _ctx, state) {
  main.append(header("The Loft", state)); // the top bar: title + the identity
  // drafts are for the person who claimed them; sensitive items (PRD §6/§10)
  // are catalogued and searchable but never on serendipity surfaces
  const items = published(state.items).filter((it) => !it.sensitive);
  const moment = todayMoment(items);
  const recent = sortByRecorded(items).slice(0, 5); // recently added, not recently dated
  const doors = [
    ["timeline", "Timeline", "The spine — every year, every week."],
    ["cast", "Family Tree", "The cast — who's who, and how they're related."],
    ["places", "Places", "The geography of a life."],
    ["themes", "Themes", "Curated ways in — letters, photos and memories together."],
    ["museum", "Museum", "The heirlooms and the objects."],
    ["letters", "Letters", "The written archive from the loft."],
  ];

  // Build the doors section, then add the review door asynchronously
  const doorGrid = el("div", { class: "door-grid" });
  const doorSection = el("section", {}, [sectionTitle("The doors"), doorGrid]);
  doors.map(([route, label, note]) =>
    doorGrid.append(
      el("a", { class: "door", href: `#/${route}` }, [
        el("span", { class: "door-label" }, label),
        el("span", { class: "door-note" }, note),
      ]),
    ),
  );
  // The portal (UR2): ONE door to the review hub. It is built synchronously
  // and is always present — the link must never disappear because the work
  // count failed or because nothing is waiting. The fetch only names the
  // work; the hub is the page that enumerates it.
  const portalNote = el("div", { class: "review-card-note" }, "Open the review hub");
  const portalSection = el("section", { class: "block review-promo" }, [
    el("a", { class: "review-card", href: "#/review" }, [
      el("div", { class: "review-card-icon" }, "✓"),
      el("div", { class: "review-card-main" }, [
        el("div", { class: "review-card-title" }, "Review"),
        portalNote,
      ]),
    ]),
  ]);
  (async () => {
    let batches;
    try {
      const res = await fetch("/api/sync/batches", { headers: { Accept: "application/json" } });
      if (!res.ok) return;
      batches = (await res.json()).batches || [];
    } catch {
      // the link stays; the hub handles the unreachable server
      return;
    }
    const plural = (count, noun) => `${count} ${noun}${count === 1 ? "" : "s"}`;
    const waiting = [];
    const pages = pagesToCheck(batches);
    if (pages) waiting.push(`${plural(pages, "page")} to check`);
    const documents = documentsToReview(batches);
    if (documents) waiting.push(`${plural(documents, "document")} to review`);
    const entities = documentsToIdentify(state).length;
    if (entities) waiting.push(`${plural(entities, "document")} to identify`);
    // identities: the import session's proposals, and the unfinished stories
    // ride the same queue (PRD §9 F10)
    const session = pendingImports(state)[0];
    const allDrafts = drafts(state.items);
    const myDrafts = me(state) ? allDrafts.filter((d) => isMine(d, state)) : allDrafts;
    const people = proposedPeople(state).length;
    if (session && people) waiting.push(`${people} ${people === 1 ? "person" : "people"} to confirm`);
    if (myDrafts.length) {
      waiting.push(`${myDrafts.length} unfinished ${myDrafts.length === 1 ? "story" : "stories"}`);
    }
    portalNote.textContent = waiting.length ? waiting.join(" · ") : "Nothing waiting — everything is confirmed.";
  })();

  main.append(
    el("section", { class: "hero" }, [
      el("h1", { class: "hero-title" }, "The Loft"),
      el("p", { class: "hero-sub" }, "A family museum, from the boxes in the loft."),
      el(
        "button",
        {
          class: "btn",
          onclick: () => {
            const pick = items[Math.floor(Math.random() * items.length)];
            if (pick) location.assign(`#/item/${pick.id}`);
          },
        },
        "🎲 Wander the archive",
      ),
    ]),
    ...(moment ? [moment] : []),
    doorSection,
    el("section", {}, [
      sectionTitle("Search the archive"),
      el(
        "form",
        {
          class: "search-form",
          onsubmit: (ev) => {
            ev.preventDefault();
            const q = ev.target.elements.q.value.trim();
            if (q) location.assign(`#/search?q=${encodeURIComponent(q)}`);
          },
        },
        [
          el("input", { name: "q", placeholder: 'Try "migraine", "Sunlight", "Mum"…', class: "search-input" }),
          el("button", { class: "btn" }, "Search"),
        ],
      ),
    ]),
    el("section", {}, [
      sectionTitle("Recently in the archive"),
      el(
        "div",
        { class: "card-grid" },
        recent.map((item) => {
          const theme = item.themes?.[0] ? state.themes.find((t) => t.id === item.themes[0].id) : null;
          return itemCard(item, theme ? theme.title : null);
        }),
      ),
    ]),
    el(
      "footer",
      { class: "foot" },
      `${published(state.items).length} items · the full collection is still arriving. Letters and documents are added by the family; anyone can add a memory from any page.`,
    ),
  );
  // between the hero/moment/draft area and the doors
  main.insertBefore(portalSection, doorSection);
}

/** The owner's unfinished stories — where they find them after dinner
 *  (user): drafts render ONLY here and on their own page, never
 *  among the archival views. Once logins exist, this follows the login. A
 *  fresh window (no remembered narrator) is asked who they are first — the
 *  drafts are claimed by name, so incognito can still find them. */

/** The unfinished import session (user): the front page shows
 *  the session the import left behind — never the pending people list
 *  itself. The review (confirm/dismiss) lives at #/import/<id>. Visible
 *  only to the signed-in owner. */
