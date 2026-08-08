/** Item detail — the lens: zoom, transcription toggle, connections (PRD §8–9). */

import { el, header, chip, itemCard } from "../ui.js";
import { memoriesSection, openDraft } from "../memories.js";
import { linkMentions } from "../people.js";
import { renderMarkdown } from "../markdown.js";
import { assetUrl, catalogued, isMine, published as publishedItems, typeLabel } from "../data.js";
import { clarificationsFor, evidenceFor, referencedBy } from "../connections.js";
import { dateLabel, sortByDate, yearOf } from "../date.js";

export function render(main, ctx, state) {
  const item = state.byId.get(ctx.arg);
  if (!item) {
    main.append(header("Item", state), el("p", { class: "empty" }, "Not found."));
    return;
  }
  // a draft is for the person who claimed it (user, 2026-08-03): the owner
  // sees everything and can finish it; anyone else gets the banner alone —
  // the title and the unverified words never render for a visitor
  // (reviewer, 2026-08-03)
  const mine = item.status === "draft" && isMine(item, state);
  main.append(header(mine || item.status !== "draft" ? item.title : "Unfinished story", state));
  // the description is the "what is this" line — under the title, above the
  // scan and the transcription (2026-08-05); a draft's words never render
  // for anyone but its narrator, same gate as the title (review, 2026-08-07)
  if (item.description && (mine || item.status !== "draft"))
    main.append(el("p", { class: "lede" }, item.description));

  if (item.status === "draft") {
    main.append(
      el("section", { class: "block" }, [
        el("p", { class: "memories-note" }, "Unfinished — a draft, visible only to the person who started it."),
        mine
          ? el("button", { class: "btn btn-primary", onclick: () => openDraft(state, item) }, "Continue this story")
          : null,
      ]),
    );
    if (!mine) {
      // the account, details and responses are the narrator's words — hidden
      // until they verify and save; the visitor sees only the banner
      main.append(
        el("section", { class: "block" }, [
          el("p", { class: "story" }, "The words of this draft stay private until it is finished."),
        ]),
      );
      return;
    }
  }

  // --- the viewer: artifact first, readability on demand ---
  let zoomed = false;
  let assetIndex = 0;
  const assets = item.assets ?? [];
  const asset = assets[0] ?? null;
  // No asset → no <img> at all: src="" would make the browser request the
  // current page URL and render a broken-image icon. The caption carries the
  // scans-pending state instead, and zoom is pointless without an image.
  const img = asset ? el("img", { class: "lens-img", src: assetUrl(item.id, asset.file), alt: item.title }) : null;
  const assetTitle = el(
    "div",
    { class: "lens-caption" },
    asset?.caption ?? (asset ? "" : "No scans yet — catalogued, scans pending."),
  );
  const zoomBtn = asset ? el("button", { class: "lens-btn" }, "🔍 Zoom") : null;
  const viewer = el("div", { class: "lens" }, [img, assetTitle, zoomBtn]);

  const showAsset = (i) => {
    if (assets.length === 0) return;
    assetIndex = (i + assets.length) % assets.length;
    const next = assets[assetIndex];
    img.src = assetUrl(item.id, next.file);
    assetTitle.textContent = next.caption ?? "";
    // a new page starts un-zoomed — the zoom state must not carry over
    zoomed = false;
    img.classList.remove("zoomed");
    zoomBtn.textContent = "🔍 Zoom";
  };
  if (img) {
    img.addEventListener("click", () => {
      zoomed = !zoomed;
      img.classList.toggle("zoomed", zoomed);
      zoomBtn.textContent = zoomed ? "🔍 Out" : "🔍 Zoom";
    });
    zoomBtn.addEventListener("click", () => img.dispatchEvent(new MouseEvent("click")));
  }

  main.append(
    el("section", {}, [
      viewer,
      assets.length > 1
        ? el("div", { class: "lens-nav" }, [
            el("button", { class: "lens-btn", onclick: () => showAsset(assetIndex - 1) }, "‹ Previous"),
            el("button", { class: "lens-btn", onclick: () => showAsset(assetIndex + 1) }, "Next ›"),
          ])
        : null,
    ]),
  );

  // --- transcription: pattern discovery lives here ---
  if (item.transcription) {
    let open = false;
    const isDraft = item.transcription_status === "draft";
    const note = isDraft
      ? el("div", { class: "draft-note" }, "Draft transcription — machine-read, not yet verified.")
      : null;
    // the transcription is verbatim markdown (a medal card is a table) —
    // render the structure, then link the mentions inside each piece
    const text = el("div", { class: "transcription-text" });
    for (const node of renderMarkdown(item.transcription)) {
      if (node.tagName === "TABLE") {
        for (const cell of node.querySelectorAll("th, td")) {
          cell.replaceChildren(...linkMentions(cell.textContent, state.people, state.places));
        }
        text.append(node);
      } else {
        const p = el("p", { class: "transcription-text" });
        p.append(...linkMentions(node.textContent, state.people, state.places));
        text.append(p);
      }
    }
    const body = el("div", { class: "transcription", hidden: true }, [note, text].filter(Boolean));
    const toggle = el(
      "button",
      {
        class: "toggle",
        onclick: () => {
          open = !open;
          body.hidden = !open;
          toggle.textContent = open
            ? isDraft
              ? "Hide draft"
              : "Hide transcription"
            : isDraft
              ? "Read the draft"
              : "Read the letter";
        },
      },
      isDraft ? "Read the draft" : "Read the letter",
    );
    main.append(el("section", { class: "block" }, [el("h3", { class: "block-title" }, "The letter"), toggle, body]));
  }

  if (item.story) {
    const by = item.told_by ? state.people.find((p) => p.id === item.told_by) : null;
    // attribution and dates are the point of a story — make them visible, and
    // keep the account's paragraph breaks (the sheet assembles Q&A verbatim)
    const meta = [
      by ? `Told by ${by.name}` : null,
      item.type === "story" ? dateLabel(item) : null,
      item.type === "story" && item.recorded ? `recorded ${item.recorded}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    const paras = item.story.split(/\n\n+/).map((p) => el("p", { class: "story" }, p));
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, item.type === "story" ? "The account" : "The story"),
        meta ? el("div", { class: "card-meta" }, meta) : null,
        ...paras,
      ]),
    );
  }
  if (item.provenance || item.sources?.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "Provenance"),
        item.provenance ? el("p", { class: "story" }, item.provenance) : null,
        item.sources?.length
          ? el(
              "ul",
              { class: "sources" },
              item.sources.map((s) =>
                el("li", {}, [
                  el("a", { href: s.url, rel: "noreferrer" }, s.title || s.url.replace(/^https?:\/\//, "")),
                  el("span", { class: "card-meta" }, ` · accessed ${s.accessed}`),
                ]),
              ),
            )
          : null,
      ]),
    );
  }

  // what this item responds to (a testimony commenting on a letter, say)
  if (item.comment_on) {
    const target = state.byId.get(item.comment_on);
    if (target) {
      main.append(
        el("section", { class: "block" }, [
          el("h3", { class: "block-title" }, "In response to"),
          el("a", { class: "reader-open", href: `#/item/${target.id}` }, target.title),
        ]),
      );
    }
  }

  // --- metadata: dates, people, places, themes, artifacts ---
  main.append(
    el("section", { class: "block" }, [
      el("h3", { class: "block-title" }, "Details"),
      el("dl", { class: "details" }, [
        el("div", {}, [el("dt", {}, "Date"), el("dd", {}, dateLabel(item))]),
        el("div", {}, [el("dt", {}, "Type"), el("dd", {}, typeLabel(item.type))]),
        item.source ? el("div", {}, [el("dt", {}, "Source"), el("dd", {}, item.source)]) : null,
        item.people?.length
          ? el("div", {}, [
              el("dt", {}, "People"),
              el(
                "dd",
                { class: "chips-inline" },
                item.people.map((p) => chip(state.people.find((q) => q.id === p.id)?.name ?? p.id, `#/person/${p.id}`)),
              ),
            ])
          : null,
        item.places?.length
          ? el("div", {}, [
              el("dt", {}, "Places"),
              el(
                "dd",
                { class: "chips-inline" },
                item.places.map((p) => chip(state.places.find((q) => q.id === p.id)?.name ?? p.id, `#/place/${p.id}`)),
              ),
            ])
          : null,
        item.themes?.length
          ? el("div", {}, [
              el("dt", {}, "Stories"),
              el(
                "dd",
                { class: "chips-inline" },
                item.themes.map((t) => chip(state.themes.find((q) => q.id === t.id)?.title ?? t.id, `#/theme/${t.id}`)),
              ),
            ])
          : null,
        item.items?.length
          ? el("div", {}, [
              el("dt", {}, "Artifacts"),
              el(
                "dd",
                { class: "chips-inline" },
                item.items.map((i) => chip(state.byId.get(i.id)?.title ?? i.id, `#/item/${i.id}`)),
              ),
            ])
          : null,
        item.facts?.some((f) => f.kind === "dob")
          ? el("div", {}, [
              el("dt", {}, "Date of birth"),
              el(
                "dd",
                { class: "chips-inline" },
                item.facts
                  .filter((f) => f.kind === "dob")
                  .map((f) => {
                    const value = f.value ?? "not parsed — needs a person's word";
                    const status = f.status === "confirmed" ? "confirmed by the narrator" : "proposed";
                    return chip(`${value} (${status})`);
                  }),
              ),
            ])
          : null,
      ]),
    ]),
  );

  // --- responses: dated, attributed stories about this item (PRD §19) ---
  // comment_on = responding to it. An items ref is an attestation (the
  // story names this artifact) and renders in "Referenced by" — never in
  // both (2026-08-06: double-render fix). Drafts never render as finished
  // responses (user, 2026-08-03).
  const published = publishedItems(state.items);
  const responses = published.filter((it) => it.comment_on === item.id);
  main.append(
    memoriesSection(state, {
      title: "Responses",
      stories: responses,
      buttonLabel: "Add your memory",
      anchor: { kind: "item", id: item.id, name: item.title },
    }),
  );

  // --- clarification fragments that attest this item (2026-08-06) ---
  const clarifications = clarificationsFor(catalogued(state.items), item.id);
  if (clarifications.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "Clarifications"),
        el(
          "div",
          { class: "clarifications" },
          clarifications.map((c) => {
            const by = state.people.find((p) => p.id === c.told_by);
            const told = c.recorded ? ` · told ${c.recorded}` : "";
            return el("div", { class: "clarification" }, [
              el("p", { class: "story" }, c.story),
              el("div", { class: "card-meta" }, `${by ? `Told by ${by.name}` : "Told"}${told}`),
            ]);
          }),
        ),
      ]),
    );
  }

  // --- connections: same people, same place, same era (PRD §8) ---
  // Collect every match, then sort by year proximity: a chronological walk
  // stopped at 6 fills "Nearby" with the oldest letters inside a long
  // same-author run and the same-era condition never wins.
  const year = yearOf(item);
  const responds = (other) => other.comment_on === item.id || other.items?.some((x) => x.id === item.id);
  const related = sortByDate(published)
    .filter((other) => other.id !== item.id && !other.sensitive) // PRD §6: never on suggested surfaces
    .filter((other) => !responds(other)) // responses render once, in the Responses block (2026-08-06)
    .filter((other) => {
      const otherYear = yearOf(other);
      if (!Number.isFinite(otherYear)) return false;
      const sharedPeople = item.people?.some((p) => other.people?.some((q) => q.id === p.id));
      const sharedPlace = item.places?.some((p) => other.places?.some((q) => q.id === p.id));
      const sameEra = Math.abs(otherYear - year) <= 1;
      return sharedPeople || sharedPlace || sameEra;
    })
    .sort((a, b) => Math.abs(yearOf(a) - year) - Math.abs(yearOf(b) - year))
    .slice(0, 6);
  if (related.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "Nearby in the archive"),
        el(
          "div",
          { class: "card-grid" },
          related.map((r) => itemCard(r)),
        ),
      ]),
    );
  }

  // the back link: everything that references this item (2026-08-06) —
  // All links are bidirectional: the boat story names Sunlight, and
  // Sunlight's page shows who attests it. comment_on items already render
  // in Responses; an item with both links renders once (2026-08-06).
  const referrers = referencedBy(catalogued(state.items), item.id).filter(
    (r) => r.id !== item.id && !r.comment_on && !r.clarification && !r.evidence,
  );
  if (referrers.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "Referenced by"),
        el(
          "div",
          { class: "card-grid" },
          referrers.map((r) => itemCard(r)),
        ),
      ]),
    );
  }

  // --- evidence records that attest this item (2026-08-06) ---
  const evidence = evidenceFor(catalogued(state.items), item.id);
  if (evidence.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "Evidence"),
        el("div", { class: "card-grid" }, evidence.map((e) => itemCard(e))),
      ]),
    );
  }
}
