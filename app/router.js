/**
 * Tiny hash router — works on any static host, no server rewrites (TECH-SPEC §2).
 * Routes: #/home, #/timeline[/year], #/item/<id>, #/person/<id>, #/place/<id>,
 *         #/themes, #/theme/<id>, #/museum, #/search?q=..., #/curator
 */

export function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const [name, ...rest] = pathPart.split("/").filter(Boolean);
  const params = new URLSearchParams(queryPart ?? "");
  return { name: name || "home", arg: rest[0] ?? null, query: params };
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

export function onRoute(handler) {
  current = handler;
  window.addEventListener("hashchange", render);
  render();
}

/**
 * Maintain the in-app stack by VALUE, so the browser's own back/forward
 * can't desync it: if the current hash is already in the stack (a revisit
 * via browser back/forward, or the home button), truncate the stack back to
 * it; otherwise record a new page. goBack then always pops real in-app
 * history and never leaves the app (PRD F1).
 */
function render() {
  if (!current) return;
  const hash = location.hash;
  const idx = stack.lastIndexOf(hash);
  if (idx >= 0 && idx < stack.length - 1) {
    stack.length = idx + 1;
  } else if (stack[stack.length - 1] !== hash) {
    stack.push(hash);
  }
  current(parseHash());
}

/** Pop the in-app stack; fall back to Home when there is no in-app history. */
export function goBack() {
  stack.pop(); // the current entry
  // `||` not `??`: the stack's oldest entry is '' on a first visit (no hash
  // fragment), and an empty target would drop the URL's fragment — a browser
  // back then exits the site. Anything falsy falls back to Home (PRD F1).
  const target = stack.pop() || "#/home";
  stack.push(target);
  if (location.hash === target) {
    render();
  } else {
    location.hash = target;
  }
}
