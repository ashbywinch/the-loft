/**
 * The Loft — boot + route dispatch.
 * Loads the projection once, then renders views into #app on hash change.
 */

import { loadBootstrap, loadData, loadTranscripts } from "./data.js";
import { onRoute, parseHash } from "./router.js";
import { el } from "./ui.js";
import { gateScreen } from "./gate.js";
import { loadLeaflet } from "./leaflet.js";
import { render as home } from "./views/home.js";

// The home is the only view in the boot bundle; every other view is imported
// on its first navigation. The review surface alone is ~120 KB — a phone
// should not download it to see the front door.
const LOADERS = {
  timeline: () => import("./views/timeline.js"),
  item: () => import("./views/item.js"),
  cast: () => import("./views/cast.js"),
  person: () => import("./views/cast.js"),
  tree: () => import("./views/tree.js"),
  places: async () => {
    try {
      await loadLeaflet();
    } catch (error) {
      // the view renders its SVG dot fallback when Leaflet cannot load;
      // the failure still has to be diagnosable
      console.error("leaflet: could not load — using the SVG fallback", error);
    }
    return import("./views/places.js");
  },
  place: () => import("./views/places.js"),
  themes: () => import("./views/stories.js"),
  theme: () => import("./views/stories.js"),
  story: () => import("./views/stories.js"),
  museum: () => import("./views/museum.js"),
  letters: () => import("./views/letters.js"),
  search: () => import("./views/search.js"),
  curator: () => import("./views/curator.js"),
  import: () => import("./views/import.js"),
  identify: () => import("./views/identify.js"),
  review: () => import("./views/review.js"),
  rows: () => import("./views/rows.js"),
};
const VIEW_EXPORT = { person: "personPage", place: "placePage", theme: "themePage", story: "reader" };

/** The identity at boot: null = unknown, {authenticated:
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
  const initial = parseHash();
  const emptyState = (me) => ({
    items: [],
    people: [],
    places: [],
    themes: [],
    relationships: [],
    imports: [],
    transcripts: {},
    byId: new Map(),
    me,
  });
  let state = emptyState(null);
  let signedIn;
  let dataLoaded = false;
  let dataError = null;
  let dataReady = null;
  const markData = () => {
    dataLoaded = true;
    mark(`data loaded (${state.items.length} items, ${state.people.length} people)`);
  };
  const ensureData = () => {
    if (!dataReady) {
      dataReady = loadBootstrap()
        .then(async (answer) => {
          if (answer.noApi) {
            Object.assign(state, await loadData());
            state.me = null;
          } else if (!answer.signedIn) {
            dataError = new Error("sign in to read the archive");
            return;
          } else {
            Object.assign(state, answer.state);
          }
          markData();
        })
        .catch((error) => {
          dataError = error;
          console.error("boot: failed to load the archive", error);
        });
    }
    return dataReady;
  };
  let transcriptsLoaded = false;
  let transcriptsError = null;
  let transcriptsReady = null;
  const ensureTranscripts = () => {
    if (!transcriptsReady) {
      transcriptsReady = loadTranscripts()
        .then((texts) => {
          state.transcripts = texts;
          transcriptsLoaded = true;
        })
        .catch((error) => {
          transcriptsError = error;
          console.error("boot: failed to load the transcriptions", error);
        });
    }
    return transcriptsReady;
  };
  if (initial.name === "rows") {
    // The row screen needs its batch's drafts and image, not the archive
    // projection. It asks only who is signed in (the header avatar).
    const identity = await fetchIdentity();
    if (identity === null) {
      document.getElementById("app").replaceChildren(gateScreen());
      return;
    }
    signedIn = identity === NO_API ? null : identity;
    state = emptyState(signedIn);
  } else {
    // One bootstrap request: identity + the projection. The old boot paid
    // one auth request and five data requests before the home could render.
    mark("bootstrap");
    let answer;
    try {
      answer = await loadBootstrap();
    } catch (error) {
      // Two-tier failure: the visitor's line and the root cause in the log.
      console.error("boot: failed to load the archive", error);
      const bootRoot = document.getElementById("app");
      bootRoot.replaceChildren(
        el(
          "div",
          { class: "empty" },
          `Could not load the archive (${error.message}). Reload to retry.`,
        ),
      );
      return;
    }
    if (answer.noApi) {
      Object.assign(state, await loadData());
      state.me = null;
      dataLoaded = true;
      markData();
    } else if (!answer.signedIn) {
      document.getElementById("app").replaceChildren(gateScreen());
      return;
    } else {
      Object.assign(state, answer.state);
      dataLoaded = true;
      dataReady = Promise.resolve();
      markData();
    }
  }
  const root = document.getElementById("app");
  const cleanups = new Map(); // route -> the view's cleanup (map, pane observer)
  let currentRoute = null;
  let routeToken = 0;
  onRoute(async (ctx, revisit) => {
    const name = LOADERS[ctx.name] ? ctx.name : "home";
    const token = ++routeToken;
    mark(`route "${name}" → ${ctx.arg ?? ""}`.trim());
    const previous = currentRoute;
    currentRoute = name;
    if (previous) {
      const cleanup = cleanups.get(previous);
      if (cleanup) {
        cleanups.delete(previous);
        cleanup(); // views with long-lived resources unhook here
      }
    }
    root.replaceChildren();
    const main = el("main", { class: "view" });
    root.append(main);
    try {
      if (name !== "rows" && !dataLoaded) {
        // a deep link to the row screen skipped the projection; the first
        // browse route fetches it, visibly
        main.append(el("div", { class: "empty" }, "Loading the archive…"));
        await ensureData();
        if (token !== routeToken) return; // a newer navigation won
        main.replaceChildren();
        if (dataError) {
          main.append(el("div", { class: "empty" }, `Could not load the archive (${dataError.message}).`));
          return;
        }
      }
      if (["item", "search", "identify", "story", "import"].includes(name) && !transcriptsLoaded) {
        main.append(el("div", { class: "empty" }, "Loading the text…"));
        await ensureTranscripts();
        if (token !== routeToken) return; // a newer navigation won
        main.replaceChildren();
        if (transcriptsError) {
          main.append(el("div", { class: "empty" }, `Could not load the text (${transcriptsError.message}).`));
          return;
        }
      }
      let view = home;
      if (name !== "home") {
        main.append(el("div", { class: "empty" }, "Loading…"));
        const module = await LOADERS[name]();
        if (token !== routeToken) return; // a newer navigation won
        if (module.cleanup) cleanups.set(name, module.cleanup);
        main.replaceChildren();
        view = module[VIEW_EXPORT[name] ?? "render"];
      }
      view(main, ctx, state);
    } catch (error) {
      // Two-tier failure (docs/coding-standards.md): a plain line for the
      // visitor, the root cause in the log — a view crash is never a blank page.
      console.error(`app: view "${name}" failed`, error);
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
    // of a long list instead of where they were (PRD §8; Baymard
    // product-list refinding; MFA11y: don't fight restoration).
    if (!revisit) window.scrollTo(0, 0);
  });
  mark("route wired");
  // From here a view's own error handler owns the page; the boot diagnostic
  // must not wipe a working app on a later unrelated click/async error.
  window.__loftReady = true;
}
