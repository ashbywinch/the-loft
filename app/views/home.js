/** Home — the front door: today's moment, wander, recent, the doors (PRD §8). */

import { el, header, itemCard, sectionTitle } from "../ui.js";
import { monthDayDistance, sortByRecorded } from "../date.js";
import { drafts, isMine, me, pendingImports, proposedPeople, published } from "../data.js";

function todayMoment(items) {
  const now = new Date();
  let best = null;
  let bestDelta = Infinity;
  for (const item of items) {
    // A story's moment-worthy date is the events' date, never the day it was
    // told: a story whose date equals its recorded/created stamp has no
    // distinct event date and is not an anniversary (2026-08-05).
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
  // read on Jan 1 keeps its correct year (review: off-by-one at New Year).
  const anniversary = new Date(now.getFullYear(), now.getMonth(), now.getDate() + best.delta);
  const years = anniversary.getFullYear() - Number.parseInt(best.item.date.slice(0, 4), 10);
  // An anniversary requires a past year: an item dated this year (a story
  // told this week) is not history — "0 years ago this week" is a lie, and a
  // fresh testimony is not a memory card (2026-08-05).
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
  main.append(header("The Loft", state)); // the top bar: title + the identity (2026-08-06)
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
  // The review door appears when there are batches awaiting review — a
  // different use case from browsing (user, 2026-08-15), but the same app
  // and the same auth. The fetch is fire-and-forget: a 401 means the user
  // isn't signed in (no review to show), and an empty response means no
  // work to do.
  let reviewSection = null;
  (async () => {
    try {
      const res = await fetch("/api/sync/batches", { headers: { Accept: "application/json" } });
      if (!res.ok) return;
      const data = await res.json();
      const pending = (data.batches || []).filter((b) => b.status !== "confirmed");
      if (!pending.length && !pendingImports(state).length) return;
      const docCount = pending.reduce(
        (n, b) => n + ((b.boundaries || []).filter((x) => x.status !== "confirmed").length),
        0,
      );
      const importSessions = pendingImports(state);
      const importCount = importSessions.length;
      const allDrafts = drafts(state.items);
      const signedIn = me(state);
      const myDrafts = signedIn ? allDrafts.filter((d) => isMine(d, state)).length : allDrafts.length;
      let note = "";
      const parts = [];
      if (docCount) parts.push(`${docCount} document${docCount === 1 ? "" : "s"}`);
      if (importCount) parts.push(`${importCount} import${importCount === 1 ? "" : "s"}`);
      if (myDrafts) parts.push(`${myDrafts} draft${myDrafts === 1 ? "" : "s"}`);
      note = parts.join(" + ") + " to review";
      if (!parts.length && importSessions.length) {
        const people = proposedPeople(state).length;
        note = `${people} identit${people === 1 ? "y" : "ies"} to confirm (import session)`;
      }
      reviewSection = el("section", { class: "block review-promo" }, [
        el(
          "a",
          { class: "review-card", href: "#/review" },
          [
            el("div", { class: "review-card-icon" }, "✓"),
            el("div", { class: "review-card-main" }, [
              el("div", { class: "review-card-title" }, "Review"),
              el("div", { class: "review-card-note" }, note),
            ]),
          ],
        ),
      ]);
      // insert between the hero/moment/draft area and the doors
      const heroSection = main.querySelector(".hero");
      const doorSection = main.querySelector(".door-grid")?.parentElement;
      if (heroSection && doorSection) {
        main.insertBefore(reviewSection, doorSection);
      } else {
        main.append(reviewSection);
      }
    } catch {
      // server unreachable — no review section, the browse surface still works
    }
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
}

/** The owner's unfinished stories — where they find them after dinner
 *  (user, 2026-08-03): drafts render ONLY here and on their own page, never
 *  among the archival views. Once logins exist, this follows the login. A
 *  fresh window (no remembered narrator) is asked who they are first — the
 *  drafts are claimed by name, so incognito can still find them. */


/** The unfinished import session (user, 2026-08-07): the front page shows
 *  the session the import left behind — never the pending people list
 *  itself. The review (confirm/dismiss) lives at #/import/<id>. Visible
 *  only to the signed-in owner. */
