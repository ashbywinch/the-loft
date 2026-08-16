/**
 * Tiny hash router — works on any static host, no server rewrites (TECH-SPEC §2).
 * Routes: #/home, #/timeline[/year], #/item/<id>, #/person/<id>, #/place/<id>,
 *         #/themes, #/theme/<id>, #/museum, #/search?q=..., #/curator
 */

export function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const rest = pathPart.split("/").filter(Boolean);
  const [name, ...more] = rest;
  const params = new URLSearchParams(queryPart ?? "");
  return { name: name || "home", arg: more[0] ?? null, rest, query: params };
}

export function navigate(hash) {
  // Accept both bare paths ("place/pl-x") and hash-prefixed ones ("#/place/pl-x")
  const path = hash.replace(/^#\/?/, "").replace(/^\/?/, "");
  const target = `#/${path}`;
  if (location.hash === target) {
    render();
  } else {
    location.hash = target;
  }
}

let current = null;
let stack = []; // in-app history, oldest first

// The logical parent per route — the Up target when a page is reached
// directly (a deep link, PRD §8 2026-08-16). Up navigates the app's
// hierarchy, never the history, so a user who lands sideways (or wanders
// item→person→item→place for ages) always has a stable way out — the
// browser Back only retraces the immediate path (Android's Back-vs-Up
// guidance).
const PARENTS = {
  person: "cast",
  place: "places",
  theme: "themes",
  story: "stories",
  review: "review", // an arg'd review route's parent is the review hub
};

export function onRoute(handler) {
  current = handler;
  window.addEventListener("hashchange", render);
  render();
}

/** Whether the back arrow returns to a real in-app page (history) — false
 * on a deep link, where the back instead goes UP to the logical parent.
 * The views use this to choose the back button's label (PRD §8 2026-08-16):
 * with history a plain "←" undoes the previous action (NN/g); without it,
 * the button names the Up destination ("← Family Tree"). */
export function canGoBackInApp() {
  return stack.length > 1;
}

/**
 * Maintain the in-app stack by VALUE, so the browser's own back/forward
 * can't desync it: if the current hash is already in the stack (a revisit
 * via browser back/forward, or the home button), truncate the stack back to
 * it; otherwise record a new page. The second argument tells the caller
 * whether this was a back/forward REVISIT — the app must not scroll to top
 * on revisits, or it fights the browser's scroll restoration and the user
 * lands at the top of a long list instead of where they were (Baymard:
 * product-list refinding; MFA11y: don't fight restoration).
 */
function render() {
  if (!current) return;
  const hash = location.hash;
  const idx = stack.lastIndexOf(hash);
  let revisit = false;
  if (idx >= 0 && idx < stack.length - 1) {
    stack.length = idx + 1;
    revisit = true;
  } else if (stack[stack.length - 1] !== hash) {
    stack.push(hash);
  }
  current(parseHash(), revisit);
}

/** Pop the in-app stack; when there is no in-app history before this page
 * (a deep link or a fragment-less first visit), go UP to the page's logical
 * parent — never Home unconditionally, and never out of the app (PRD F1). */
export function goBack() {
  stack.pop(); // the current entry
  // One source of truth (PRD §8, 2026-08-16): the in-app back is the SAME
  // traversal as the browser back — never a new history entry. Every in-app
  // navigation changed the hash, so the browser history holds the previous
  // in-app page; history.back() pops to it and the render handler re-syncs
  // the stack.
  const previous = stack[stack.length - 1];
  if (!previous) {
    const { name, arg } = parseHash();
    let up = PARENTS[name];
    if (name === "review" && !arg) up = null; // the hub is a top-level door
    const target = up ? `#/${up}` : "#/home";
    if (location.hash === target) {
      render();
    } else {
      location.hash = target;
    }
    return;
  }
  history.back();
}
