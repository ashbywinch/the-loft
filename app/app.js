/**
 * The Loft — boot + route dispatch.
 * Loads the projection once, then renders views into #app on hash change.
 */

import { loadData } from "./data.js";
import { onRoute } from "./router.js";
import { el } from "./ui.js";
import { gateScreen } from "./gate.js";
import { render as home } from "./views/home.js";
import { render as timeline } from "./views/timeline.js";
import { render as item } from "./views/item.js";
import { render as cast, personPage } from "./views/cast.js";
import { render as tree } from "./views/tree.js";
import { render as places, placePage, cleanup as cleanupPlaces } from "./views/places.js";
import { render as stories, themePage, reader } from "./views/stories.js";
import { render as museum } from "./views/museum.js";
import { render as letters } from "./views/letters.js";
import { render as search } from "./views/search.js";
import { render as curator } from "./views/curator.js";
import { render as importReview } from "./views/import.js";
import { render as review, cleanup as cleanupReview } from "./views/review.js";

const ROUTES = {
  home,
  timeline,
  item,
  cast,
  tree,
  person: personPage,
  places,
  place: placePage,
  themes: stories,
  theme: themePage,
  story: reader,
  museum,
  letters,
  search,
  curator,
  import: importReview,
  review,
};

/** The identity at boot (2026-08-06): null = unknown, {authenticated:
 *  true} = signed in, or the sentinel NO_API when the deployment has no
 *  auth server (the static host) — that case stays open, because there is
 *  nothing to sign in against. A definitive "not authenticated" gates the
 *  whole archive behind the sign-in screen. */
export const NO_API = Symbol("no-auth-server");

export async function fetchIdentity() {
  // a static-host deployment (app/ + data/ served with no auth server)
  // opts into open access explicitly — nothing else opens the archive
  if (typeof window !== "undefined" && window.LOFT_NO_API === true) return NO_API;
  try {
    const response = await fetch("/api/auth/me", { headers: { Accept: "application/json" } });
    if (!response.ok) {
      // a 404/410 is a plain file server with no /api route — a genuinely
      // no-API deployment; any other failure is the server saying "no"
      if (response.status === 404 || response.status === 410) return NO_API;
      return null;
    }
    // a 200 that is not JSON is ambiguous (a proxy, SSO interstitial, or
    // captive portal) — fail closed rather than expose the archive
    if (!response.headers.get("content-type")?.includes("application/json")) return null;
    const identity = await response.json();
    return identity.authenticated ? identity : null;
  } catch {
    return null; // the auth server is unreachable — fail closed, never expose the archive
  }
}

export async function boot() {
  const mark = (message) => {
    console.log("[boot]", message);
    window.__loftStage = message; // the visible loading marker repaints with this
  };
  mark("start");
  const identity = await fetchIdentity();
  mark(identity === null ? "no session — the gate" : identity === NO_API ? "open (no auth server)" : `session for ${identity.email}`);
  if (identity === null) {
    // the server says "not signed in" — the archive is private; the app
    // shell stays public so this gate can load (2026-08-06, user)
    document.getElementById("app").replaceChildren(gateScreen());
    return;
  }
  let state;
  try {
    state = await loadData();
    state.me = identity === NO_API ? null : identity;
    mark(`data loaded (${state.items.length} items, ${state.people.length} people)`);
  } catch (error) {
    // Fail visibly, never a blank page (docs/coding-standards.md: fail fast)
    const root = document.getElementById("app");
    root.replaceChildren(
      el(
        "div",
        { class: "empty" },
        `Could not load the archive (data load failed: ${error && error.message}). Reload to retry.`,
      ),
    );
    console.error("boot: failed to load the archive", error);
    return;
  }
  const root = document.getElementById("app");
  onRoute((ctx, revisit) => {
    mark(`route "${ctx.name}" → ${ctx.arg ?? ""}`.trim());
    cleanupPlaces(); // views with long-lived resources (the Leaflet map) unhook here
    cleanupReview(); // the review surface's pane observer (same rationale)
    root.replaceChildren();
    const main = el("main", { class: "view" });
    root.append(main);
    const view = ROUTES[ctx.name] ?? home;
    try {
      view(main, ctx, state);
    } catch (error) {
      // Two-tier failure (docs/coding-standards.md): a plain line for the
      // visitor, the root cause in the log — a view crash is never a blank page.
      console.error(`app: view "${ctx.name}" failed`, error);
      main.replaceChildren(
        el(
          "div",
          { class: "empty" },
          `Something went wrong showing this page (${error && error.message}). The rest of the archive is still here.`,
        ),
      );
    }
    // On a browser back/forward REVISIT the browser restores the scroll
    // position itself — forcing scrollTo(0,0) would land the user at the top
    // of a long list instead of where they were (PRD §8, 2026-08-16; Baymard
    // product-list refinding; MFA11y: don't fight restoration).
    if (!revisit) window.scrollTo(0, 0);
  });
  mark("route wired");
}
