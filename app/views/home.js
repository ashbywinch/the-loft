/** Home — the front door: today's moment, wander, recent, the doors (PRD §8). */

import { el, header, itemCard, sectionTitle } from "../ui.js";
import { monthDayDistance, sortByRecorded } from "../date.js";
import { drafts, isMine, me, pendingImports, proposedPeople, published } from "../data.js";


/** The portal's "Check the rows" item (UR2): how many of the batches' pages
 *  wait on a check, and the surface of the first one — the page's own draw
 *  view when the batch's boundaries locate it, else the batch's list. */
export function rowsToCheck(batches) {
  const open = (batches || []).filter((b) => b.status !== "confirmed" && (b.pages_pending || []).length);
  const count = open.reduce((n, b) => n + b.pages_pending.length, 0);
  if (!count) return null;
  for (const batch of open) {
    const boundaries = batch.boundaries || [];
    for (let doc = 0; doc < boundaries.length; doc += 1) {
      const page = (boundaries[doc].pages || []).findIndex((name) => batch.pages_pending.includes(name));
      if (page >= 0) return { count, href: `#/review/${encodeURIComponent(batch.batch_id)}/${doc}/${page}` };
    }
    return { count, href: `#/review/${encodeURIComponent(batch.batch_id)}` };
  }
  return { count, href: "#/review" };
}

/** The portal's "Review the transcripts" item: the documents still awaiting
 *  the review gate, and the first one's surface. */
export function documentsToReview(batches) {
  const waiting = (batches || [])
    .filter((b) => b.status !== "confirmed")
    .flatMap((batch) =>
      (batch.boundaries || []).map((boundary, index) => ({ batch, boundary, index })),
    )
    .filter(({ boundary }) => boundary.status !== "confirmed");
  if (!waiting.length) return null;
  const first = waiting[0];
  return { count: waiting.length, href: `#/review/${encodeURIComponent(first.batch.batch_id)}/${first.index}/0` };
}


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
  // The portal (UR2): every pending human item with its count, each door
  // opening the surface that clears it. The fetch is fire-and-forget: a 401
  // means the user isn't signed in (no review work to show), and nothing
  // pending means no portal.
  const portalSection = el("section", { class: "block review-promo" });
  (async () => {
    let batches;
    try {
      const res = await fetch("/api/sync/batches", { headers: { Accept: "application/json" } });
      if (!res.ok) return;
      batches = (await res.json()).batches || [];
    } catch {
      // server unreachable — no portal; the browse surface still works
      return;
    }
    const cards = [];
    const plural = (count, noun) => `${count} ${noun}${count === 1 ? "" : "s"}`;
    const rows = rowsToCheck(batches);
    if (rows) cards.push({ href: rows.href, title: "Check the rows", note: `${plural(rows.count, "page")} to check` });
    const documents = documentsToReview(batches);
    if (documents) {
      cards.push({
        href: documents.href,
        title: "Review the transcripts",
        note: `${plural(documents.count, "document")} to review`,
      });
    }
    // identities: the import session's proposals, and the unfinished stories
    // ride this queue (PRD §9 F10)
    const session = pendingImports(state)[0];
    const allDrafts = drafts(state.items);
    const myDrafts = me(state) ? allDrafts.filter((d) => isMine(d, state)) : allDrafts;
    const people = proposedPeople(state).length;
    const notes = [];
    if (session) notes.push(people ? `${people} ${people === 1 ? "person" : "people"} to confirm` : "an import session to review");
    if (myDrafts.length) {
      notes.push(`${myDrafts.length} unfinished ${myDrafts.length === 1 ? "story" : "stories"}`);
    }
    if (notes.length) {
      const target = session ? `#/import/${encodeURIComponent(session.id)}` : `#/item/${encodeURIComponent(myDrafts[0].id)}`;
      cards.push({ href: target, title: "Identify people", note: notes.join(", ") });
    }
    if (!cards.length) return;
    portalSection.replaceChildren(
      ...cards.map(({ href, title, note }) =>
        el("a", { class: "review-card", href }, [
          el("div", { class: "review-card-icon" }, "✓"),
          el("div", { class: "review-card-main" }, [
            el("div", { class: "review-card-title" }, title),
            el("div", { class: "review-card-note" }, note),
          ]),
        ]),
      ),
    );
    // insert between the hero/moment/draft area and the doors
    const doorSection = main.querySelector(".door-grid")?.parentElement;
    if (doorSection) main.insertBefore(portalSection, doorSection);
    else main.append(portalSection);
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
 *  (user): drafts render ONLY here and on their own page, never
 *  among the archival views. Once logins exist, this follows the login. A
 *  fresh window (no remembered narrator) is asked who they are first — the
 *  drafts are claimed by name, so incognito can still find them. */

/** The unfinished import session (user): the front page shows
 *  the session the import left behind — never the pending people list
 *  itself. The review (confirm/dismiss) lives at #/import/<id>. Visible
 *  only to the signed-in owner. */
