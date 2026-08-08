/** The boot gate — shown when the server says the visitor isn't signed in
 *  (2026-08-06, user: the archive's content is gated behind sign-in; the
 *  app shell stays public so the sign-in can load). A no-API static host
 *  never renders this — boot only gates on a definitive
 *  {authenticated: false} from /api/auth/me. */

import { el } from "./ui.js";
import { signInSheet } from "./signin.js";

export function gateScreen() {
  return el("main", { class: "view gate" }, [
    el("h1", {}, "The Loft"),
    el("p", { class: "story" }, "The family archive — sign in with your Google account to read it."),
    el("p", {}, [el("button", { class: "btn btn-primary", onclick: signInSheet }, "Sign in with Google")]),
    el("p", { class: "card-meta" }, "It's a private archive for the family — your account must be in it."),
  ]);
}
