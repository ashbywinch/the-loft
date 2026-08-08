/** Search — the whole archive can be asked, not just browsed (PRD §6, §10). */

import { el, header, itemCard, emptyState } from "../ui.js";
import { published } from "../data.js";

function matches(item, q, state) {
  const hay = [
    item.title,
    item.description,
    item.story,
    state.transcripts[item.id] ?? "",
    item.people?.map((p) => state.people.find((x) => x.id === p.id)?.name ?? "").join(" "),
    item.places?.map((p) => state.places.find((x) => x.id === p.id)?.name ?? "").join(" "),
    item.themes?.map((t) => state.themes.find((x) => x.id === t.id)?.title ?? "").join(" "),
  ]
    .join(" ")
    .toLowerCase();
  return hay.includes(q);
}

export function render(main, ctx, state) {
  const q = (ctx.query.get("q") ?? "").trim().toLowerCase();
  main.append(header("Search", state));

  const form = el(
    "form",
    {
      class: "search-form",
      onsubmit: (ev) => {
        ev.preventDefault();
        const value = ev.target.elements.q.value.trim();
        location.assign(value ? `#/search?q=${encodeURIComponent(value)}` : "#/search");
      },
    },
    [
      el("input", { name: "q", value: q, placeholder: 'Try "migraine", "Sunlight", "Mum"…', class: "search-input" }),
      el("button", { class: "btn" }, "Search"),
    ],
  );
  main.append(form);

  if (!q) {
    main.append(emptyState("Search titles, transcriptions, people, places and stories."));
    return;
  }

  const results = published(state.items).filter((item) => matches(item, q, state));
  main.append(
    el("h2", { class: "section-title" }, `${results.length} result${results.length === 1 ? "" : "s"} for "${q}"`),
  );
  if (results.length === 0) {
    main.append(emptyState("Nothing yet — the full collection is still being catalogued."));
    return;
  }
  main.append(
    el(
      "div",
      { class: "card-grid" },
      results.map((item) => itemCard(item)),
    ),
  );
}
