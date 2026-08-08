/** The import review (user, 2026-08-07): one session's pending people —
 *  the owner confirms or dismisses each; the tree shows only confirmed
 *  family until then. Reached from the front-page session card. */

import { el, header } from "../ui.js";
import { proposedPeople } from "../data.js";
import { navigate } from "../router.js";

export function render(main, ctx, state) {
  const session = (state.imports ?? []).find((s) => s.id === ctx.arg);
  if (!session) {
    main.append(header("The import", state), el("p", { class: "empty" }, "Not found."));
    return;
  }
  main.append(header(session.title, state));
  const pending = proposedPeople(state);
  if (!pending.length) {
    main.append(
      el("section", { class: "block" }, [
        el("h2", { class: "block-title" }, "Everything is confirmed"),
        el("p", { class: "memories-note" }, "Nothing is waiting — the import is done."),
      ]),
    );
    return;
  }
  main.append(
    el("section", { class: "block import-pending" }, [
      el("h2", { class: "block-title" }, `${pending.length} ${pending.length === 1 ? "person" : "people"} awaiting confirmation`),
      el(
        "div",
        { class: "cast-grid" },
        pending.map((person) =>
          el("div", { class: "cast-card" }, [
            el("div", { class: "cast-name" }, person.name),
            el("div", { class: "cast-relation clamp-2" }, person.relation ?? ""),
            el("div", { class: "confirm-actions" }, [
              el("button", { class: "btn btn-primary", onclick: () => confirmPerson(state, person.id) }, "Confirm"),
              el("button", { class: "btn", onclick: () => dismissPerson(state, person.id) }, "Dismiss"),
            ]),
          ]),
        ),
      ),
    ]),
  );
}

/** Confirm: the person becomes family (status drops; confirmed records omit
 *  it). The server supersedes the archive, republishes, and returns the
 *  updated person — merge it and re-render without a reload. */
async function confirmPerson(state, id) {
  try {
    const res = await fetch("/api/people/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    if (!res.ok) throw new Error(`confirm failed: ${res.status}`);
    const body = await res.json();
    const person = body.person;
    const idx = state.people.findIndex((p) => p.id === person.id);
    if (idx >= 0) state.people[idx] = person;
    else state.people.push(person);
    // the last pending person completes the session — the server agrees, but
    // the client's merged state must too, or the card lingers until a reload
    if (proposedPeople(state).length === 0) {
      state.imports = (state.imports ?? []).map((s) => (s.status === "pending" ? { ...s, status: "reviewed" } : s));
    }
    navigate(location.hash); // re-render the current route with the merged state
  } catch (error) {
    console.error("import review: confirm failed", error);
  }
}

/** Dismiss: dropped = gone (the proposed/confirmed seam). The person and
 *  their relationships leave the archive. */
async function dismissPerson(state, id) {
  try {
    const res = await fetch("/api/people/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    if (!res.ok) throw new Error(`dismiss failed: ${res.status}`);
    state.people = state.people.filter((p) => p.id !== id);
    state.relationships = (state.relationships ?? []).filter((r) => r.a !== id && r.b !== id);
    if (proposedPeople(state).length === 0) {
      state.imports = (state.imports ?? []).map((s) => (s.status === "pending" ? { ...s, status: "reviewed" } : s));
    }
    navigate(location.hash);
  } catch (error) {
    console.error("import review: dismiss failed", error);
  }
}
