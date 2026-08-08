/** The top-bar identity (2026-08-06, user): the industry-standard shape —
 *  signed in: the person's avatar, tapped opens a small account sheet
 *  (name, email, Sign out); signed out: a compact Sign in button. The ⌂
 *  home button is gone (back + the in-app stack reach home).
 *  Plain DOM, no ui.js import: ui.js's header() includes this, and a cycle
 *  would be ui -> identity -> ui.
 */

import { me } from "./data.js";

function button(label, onclick) {
  const b = document.createElement("button");
  b.className = "btn";
  b.textContent = label;
  b.onclick = onclick;
  return b;
}

async function signIn() {
  // follow the login endpoint's auth_url — navigating to the endpoint
  // renders its JSON as a page (2026-08-06)
  try {
    const res = await fetch("/api/auth/login");
    const data = await res.json();
    if (data.auth_url) location.href = data.auth_url;
  } catch {
    // the server isn't reachable — nothing to do
  }
}

function accountSheet(state, signedIn) {
  if (document.querySelector(".account-sheet")) return;
  const person = state.people.find((p) => p.id === signedIn.person);
  const sheet = document.createElement("section");
  sheet.className = "sheet account-sheet";
  const name = document.createElement("h2");
  name.textContent = person?.name ?? signedIn.name;
  const email = document.createElement("p");
  email.className = "card-meta";
  email.textContent = signedIn.email;
  const out = button("Sign out", async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      location.reload();
    }
  });
  sheet.append(name, email, out);
  const overlay = document.createElement("div");
  overlay.className = "sheet-overlay";
  overlay.append(sheet);
  overlay.onclick = (e) => {
    if (e.target === overlay) overlay.remove();
  };
  document.body.append(overlay);
}

export function identityElement(state) {
  const signedIn = me(state);
  const wrap = document.createElement("span");
  wrap.className = "topbar-identity";
  if (!signedIn) {
    wrap.append(button("Sign in", signIn));
    return wrap;
  }
  const open = () => accountSheet(state, signedIn);
  if (signedIn.person) {
    const img = document.createElement("img");
    img.className = "topbar-avatar";
    img.src = `data/assets/avatar-${signedIn.person}.svg`;
    img.alt = signedIn.name;
    img.onclick = open;
    wrap.append(img);
    return wrap;
  }
  // signed in but not yet in the archive — the initial stands in for the
  // avatar; the sheet still carries the identity + Sign out
  const initial = document.createElement("button");
  initial.className = "topbar-avatar topbar-avatar-initial";
  initial.textContent = (signedIn.name ?? "?").trim().charAt(0).toUpperCase() || "?";
  initial.onclick = open;
  wrap.append(initial);
  return wrap;
}
