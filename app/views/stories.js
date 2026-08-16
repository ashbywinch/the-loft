/** Stories — themes as doors: the list, a theme page, and reader mode (PRD §10). */

import { el, header, itemCard, chip, emptyState } from "../ui.js";
import { memoriesSection } from "../memories.js";
import { assetUrl, published } from "../data.js";
import { renderMarkdown } from "../markdown.js";
import { aggregate, sortedCounts } from "../connections.js";
import { canGoBackInApp } from "../router.js";

export function render(main, _ctx, state) {
  main.append(header("Themes", state));
  main.append(
    el(
      "p",
      { class: "lede" },
      "Each theme groups letters, photos and memories around a part of the family's story — the original documents underneath.",
    ),
  );
  main.append(
    el(
      "div",
      { class: "theme-list" },
      state.themes.map((theme) => {
        const count = theme.items.length;
        return el("a", { class: "card theme-card", href: `#/theme/${theme.id}` }, [
          el("div", { class: "card-title" }, theme.title),
          el(
            "div",
            { class: "card-meta" },
            `${count} item${count === 1 ? "" : "s"}${theme.seeded ? " · the collection is still arriving" : " · the real slice"}`,
          ),
          el("p", { class: "story" }, theme.subtitle),
        ]);
      }),
    ),
  );
}

export function themePage(main, ctx, state) {
  const theme = state.themes.find((t) => t.id === ctx.arg);
  if (!theme) {
    main.append(header("Themes", state), el("p", { class: "empty" }, "Not found."));
    return;
  }
  main.append(header(theme.title, state, canGoBackInApp() ? true : "Themes"));
  main.append(el("p", { class: "story lede" }, theme.subtitle));
  if (theme.note) {
    main.append(
      el("div", { class: "sv-stub" }, [
        el("span", { class: "sv-label" }, "The curator's note"),
        el("span", { class: "sv-note" }, theme.note),
      ]),
    );
  }

  const resolved = theme.items.map((entry) => ({ entry, item: state.byId.get(entry.id) })).filter((row) => row.item);
  const agg = aggregate(resolved.map((r) => r.item));
  const personChips = sortedCounts(agg.people).map(([id, count]) =>
    chip(`${state.people.find((p) => p.id === id)?.name ?? id} · ${count}`, `#/person/${id}`),
  );
  const placeChips = sortedCounts(agg.places).map(([id, count]) =>
    chip(`${state.places.find((p) => p.id === id)?.name ?? id} · ${count}`, `#/place/${id}`),
  );
  const conn = el("section", { class: "block" }, []);
  if (personChips.length)
    conn.append(el("h3", { class: "block-title" }, "People"), el("div", { class: "chips" }, personChips));
  if (placeChips.length)
    conn.append(el("h3", { class: "block-title" }, "Places"), el("div", { class: "chips" }, placeChips));
  if (conn.childElementCount) main.append(conn);

  if (resolved.length >= 2) {
    main.append(
      el("button", { class: "btn", onclick: () => location.assign(`#/story/${theme.id}`) }, "▶ Read as a story"),
    );
  }

  main.append(
    el("section", {}, [
      el("h2", { class: "section-title" }, "The arrangement"),
      resolved.length
        ? el(
            "div",
            { class: "card-grid" },
            resolved.map(({ entry, item }) => itemCard(item, entry.note)),
          )
        : emptyState("The items are still being catalogued — the door is open, the room is being arranged."),
    ]),
  );

  // --- stories told about this theme (PRD §19) — never the arranged ones
  // again: an item appears once per page (2026-08-06) ---
  const stories = published(state.items).filter(
    (it) => it.type === "story" && it.themes?.some((t) => t.id === theme.id),
  );
  main.append(
    memoriesSection(state, {
      title: `Memories about ${theme.title}`,
      stories,
      buttonLabel: "Add your memory to this theme",
      anchor: { kind: "theme", id: theme.id, name: theme.title },
      exclude: resolved.map(({ entry }) => entry.id),
    }),
  );
}

export function reader(main, ctx, state) {
  const theme = state.themes.find((t) => t.id === ctx.arg);
  const rows = theme
    ? theme.items.map((entry) => ({ entry, item: state.byId.get(entry.id) })).filter((r) => r.item)
    : [];
  if (!theme || rows.length < 2) {
    main.append(header("Stories", state, canGoBackInApp() ? true : "Stories"), el("p", { class: "empty" }, "Not enough items to read yet."));
    return;
  }

  let index = 0;
  const title = el("h2", { class: "reader-title" }, "");
  const note = el("p", { class: "reader-note" }, "");
  const caption = el("div", { class: "reader-caption" }, "");
  const progress = el("div", { class: "reader-progress" }, "");
  const prev = el("button", { class: "btn" }, "‹ Previous");
  const next = el("button", { class: "btn" }, "Next ›");
  const body = el("div", { class: "reader-body" }, []);

  const show = () => {
    const { entry, item } = rows[index];
    title.textContent = item.title;
    note.textContent = entry.note || "";
    caption.textContent = `${index + 1} of ${rows.length}`;
    progress.style.width = `${((index + 1) / rows.length) * 100}%`;
    const asset = item.assets?.[0];
    const nodes = [];
    if (asset) nodes.push(el("img", { class: "reader-img", src: assetUrl(item.id, asset.file), alt: item.title }));
    if (item.transcription) nodes.push(...renderMarkdown(item.transcription));
    nodes.push(el("a", { class: "reader-open", href: `#/item/${item.id}` }, "Open the item →"));
    body.replaceChildren(...nodes);
    prev.disabled = index === 0;
    next.disabled = index === rows.length - 1;
  };
  prev.addEventListener("click", () => {
    if (index > 0) {
      index -= 1;
      show();
    }
  });
  next.addEventListener("click", () => {
    if (index < rows.length - 1) {
      index += 1;
      show();
    }
  });
  show();

  main.append(
    header(`Story — ${theme.title}`, state),
    el("div", { class: "reader" }, [
      el("div", { class: "reader-head" }, [title, note]),
      body,
      el("div", { class: "reader-foot" }, [prev, next, caption]),
      progress,
    ]),
  );
}
