/** The boot gate — shown when the server says the visitor isn't signed in
 *  (user: the archive's content is gated behind sign-in; the app shell
 *  stays public so the sign-in can load), or when the account that IS signed
 *  in is not on the family list (the archive is the household's). A no-API
 *  static host never renders this — boot only gates on a definitive
 *  {authenticated: false}, or on the private layer's 403. */

import { el } from "./ui.js";
import { signInSheet } from "./signin.js";

export function gateScreen({ notAMember = false } = {}) {
  return el("main", { class: "view gate" }, [
    el("h1", {}, "The Loft"),
    el(
      "p",
      { class: "story" },
      notAMember
        ? "You're signed in, but this archive belongs to one family — and this account isn't on its list."
        : "The family archive — sign in with your Google account to read it.",
    ),
    el("p", {}, [
      el(
        "button",
        { class: "btn btn-primary", onclick: signInSheet },
        notAMember ? "Sign in as someone else" : "Sign in with Google",
      ),
    ]),
    el(
      "p",
      { class: "card-meta" },
      notAMember
        ? "Ask the family to add this address, or sign in with the account they added."
        : "It's a private archive for the family — your account must be in it.",
    ),
  ]);
}
