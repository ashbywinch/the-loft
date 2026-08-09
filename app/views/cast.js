/** Cast — the people: family tree + person pages with full connections. */

import { el, header, chip, decadeList, itemCard } from "../ui.js";
import { captureButton } from "../memories.js";
import { aggregate, clarificationsFor, evidenceFor, itemDateFor, reflectionsFor, sortedCounts, itemInvolves } from "../connections.js";
import { ageInYears, dateLabel } from "../date.js";
import { catalogued, published } from "../data.js";
import { buildTree, defaultFocus, familyIds, narratorId } from "./tree.js";

export function render(main, _ctx, state) {
  main.append(header("Family Tree", state));
  main.append(el("p", { class: "lede" }, "The family tree — tap anyone to move it; the centre card opens their page."));
  main.append(
    buildTree(state, defaultFocus(state, narratorId(state)), { narratorId: narratorId(state) }),
  );

  // people the tree can't place (no family edges yet) stay browsable;
  // proposed people are a pending import, not "also in the archive" — they
  // live on the home page until confirmed (2026-08-07, user)
  const inTree = familyIds(state);
  const others = state.people.filter((p) => !inTree.has(p.id) && p.status !== "proposed");
  if (others.length) {
    main.append(el("h3", { class: "block-title" }, "Also in the archive"));
    main.append(
      el(
        "div",
        { class: "cast-grid" },
        others.map((person) =>
          el("a", { class: "cast-card", href: `#/person/${person.id}` }, [
            el("img", { class: "avatar", src: `data/assets/avatar-${person.id}.svg`, alt: person.name }),
            el("div", { class: "cast-name" }, person.name),
            // clamp-2: a long relation must not stretch the card and its
            // row-mates (2026-08-06, user: two tall cards in the grid)
            el("div", { class: "cast-relation clamp-2" }, person.relation),
          ]),
        ),
      ),
    );
  }
}

export function personPage(main, ctx, state) {
  const person = state.people.find((p) => p.id === ctx.arg);
  if (!person) {
    main.append(header("Family Tree", state), el("p", { class: "empty" }, "Not found."));
    return;
  }
  const items = catalogued(state.items)
    .filter((item) => itemInvolves(item, person.id))
    .sort((a, b) => itemDateFor(a, person).localeCompare(itemDateFor(b, person)));
  main.append(header(person.name, state));
  if (person.status === "proposed") {
    // a proposed person's facts are a proposal, not attested record — the
    // page is the review surface, so they render, visibly marked (2026-08-06)
    main.append(
      el("p", { class: "card-meta" }, "Proposed — awaiting confirmation. Dates and links here are deductions, not attested record."),
    );
  }
  if (person.status === "estimated" && person.basis) {
    // the estimated chip names the person and shows only what the dataset
    // records — the basis is the reviewer's own words, verbatim (2026-08-09)
    const { by, when, text } = person.basis;
    main.append(
      el("p", { class: "card-meta" }, `Estimated — from ${by}'s recollection${when ? `, ${when}` : ""}: "${text}".`),
    );
  }
  const age = (fact) => {
    const years = ageInYears(person.dob, fact);
    return years ? ` (aged ${years.exact ?? `${years.from}–${years.to}`})` : "";
  };
  const life = [
    person.dob ? `b. ${dateLabel({ date: person.dob.date, date_precision: person.dob.precision, date2: person.dob.date2 })}` : null,
    person.dod
      ? `d. ${dateLabel({ date: person.dod.date, date_precision: person.dod.precision, date2: person.dod.date2 })}${age(person.dod)}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const facts = [
    life,
    person.occupations?.length ? `Occupation: ${person.occupations.join(", ")}` : null,
    person.residence?.length
      ? `Lived: ${person.residence
          .map((r) => {
            const place = state.places.find((p) => p.id === r.place);
            const span = [r.from, r.to].filter(Boolean).join("–");
            return `${place?.name ?? r.place}${span ? `, ${span}` : ""}`;
          })
          .join("; ")}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  main.append(
    el("section", { class: "person" }, [
      el("img", { class: "avatar avatar-lg", src: `data/assets/avatar-${person.id}.svg`, alt: person.name }),
      el("div", { class: "person-body" }, [
        el("div", { class: "card-meta" }, person.relation),
        facts ? el("div", { class: "card-meta" }, facts) : null,
        person.pronouns ? el("div", { class: "card-meta" }, `Pronouns: ${person.pronouns}`) : null,
        person.aliases?.length ? el("div", { class: "card-meta" }, `Known as: ${person.aliases.join(", ")}`) : null,
        el("p", { class: "story" }, person.bio),
      ]),
    ]),
  );

  // the capture affordance lives in the header — the person's told stories
  // render once, in "Said by" below (main, 2026-08-03); drafts never render
  main.append(
    el("div", { class: "memories-cta" }, [
      captureButton(state, { kind: "person", id: person.id, name: person.name }, `Add a memory of ${person.name}`),
    ]),
  );

  const agg = aggregate(items, person.id); // places attach to the people AT them, not everyone in the item
  const name = (kind, id) => {
    // kind matches the aggregate keys: 'places' | 'themes' | 'people'
    if (kind === "places") return state.places.find((p) => p.id === id)?.name ?? id;
    if (kind === "themes") return state.themes.find((t) => t.id === id)?.title ?? id;
    return state.people.find((p) => p.id === id)?.name ?? id;
  };
  const row = (kind, title, href) => {
    const entries = sortedCounts(agg[kind]).filter(([id]) => id !== person.id);
    if (entries.length === 0) return null;
    return el("div", { class: "block" }, [
      el("h3", { class: "block-title" }, title),
      el(
        "div",
        { class: "chips" },
        entries.map(([id, count]) => chip(`${name(kind, id)} · ${count}`, `#/${href}/${id}`)),
      ),
    ]);
  };

  // People row: the attested relationships only — who this person would
  // recognise as part of their life. Co-mention in an item is not being
  // with: the 2001 email names 91 people and Beatrice Beth Kendall is not
  // linked to 90 of them (2026-08-06, the recognition principle).
  const peopleRow = (() => {
    const rels = (state.relationships ?? []).filter((r) => r.a === person.id || r.b === person.id);
    const entries = rels
      .map((r) => {
        const otherId = r.a === person.id ? r.b : r.a;
        const label = (r.a === person.id ? r.label_a : r.label_b) ?? r.kind; // never "Name — undefined"
        const p = state.people.find((q) => q.id === otherId);
        if (!p) return null;
        let text = `${p.name} — ${label}`;
        // a dated spouse edge shows the marriage date and this person's age
        // at it — calculated, never stored (2026-08-06)
        if (r.kind === "spouse" && r.date) {
          const when = dateLabel({ date: r.date.date, date_precision: r.date.precision, date2: r.date.date2 });
          const years = ageInYears(person.dob, { date: r.date.date, precision: r.date.precision });
          text += ` (m. ${when}${years ? `, aged ${years.exact ?? `${years.from}–${years.to}`}` : ""})`;
        }
        return { id: otherId, text };
      })
      .filter(Boolean);
    if (!entries.length) return null;
    return el("div", { class: "block" }, [
      el("h3", { class: "block-title" }, "People"),
      el(
        "div",
        { class: "chips" },
        entries.map((e) => chip(e.text, `#/person/${e.id}`)),
      ),
    ]);
  })();

  // rows are null when empty — append() would render a literal "null" text
  // node, so drop the empty rows.
  main.append(...[peopleRow, row("places", "Places", "place"), row("themes", "Stories", "theme")].filter(Boolean));

  // Complete and non-overlapping (2026-08-03): every item involving the
  // person lands in exactly one section — the artifacts they are IN as a
  // subject (people[], told by someone else or nobody), or the comments they
  // told (told_by them). Clarification fragments are neither — they render
  // only in their own block below (2026-08-06). Placement is by the
  // person's involvement date when the ref states one — the family record
  // sits in the 1940s on Nora's page, not the 1860s (2026-08-06); the
  // clone carries the date through the decade bands and the card labels.
  const involved = published(state.items)
    .filter((item) => itemInvolves(item, person.id))
    .map((item) => ({ ...item, date: itemDateFor(item, person) }))
    .sort((a, b) => a.date.localeCompare(b.date));
  const artifacts = involved.filter((item) => item.told_by !== person.id);
  const said = involved.filter((item) => item.told_by === person.id);

  main.append(
    el("section", {}, [
      el("h2", { class: "section-title" }, `Artifacts with ${person.name} — ${artifacts.length}`),
      artifacts.length
        ? decadeList(artifacts, `#/timeline?person=${person.id}`)
        : el("p", { class: "empty" }, "Nothing catalogued yet."),
    ]),
  );

  if (said.length) {
    main.append(
      el("section", {}, [
        el("h2", { class: "section-title" }, `Said by ${person.name} — ${said.length}`),
        decadeList(said, `#/timeline?type=story&person=${person.id}`),
      ]),
    );
  }

  // --- clarification fragments that attest this person (2026-08-06) ---
  const clarifications = clarificationsFor(catalogued(state.items), person.id);
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

  // --- reflections that mention this person (2026-08-06) ---
  const reflections = reflectionsFor(catalogued(state.items), person.id);
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

  // --- evidence records that attest this person (2026-08-06) ---
  const evidence = evidenceFor(catalogued(state.items), person.id);
  if (evidence.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h3", { class: "block-title" }, "Evidence"),
        el("div", { class: "card-grid" }, evidence.map((e) => itemCard(e))),
      ]),
    );
  }
}
