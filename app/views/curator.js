/** Curator — stubbed for the prototype (TECH-SPEC §13): real mode is Google
 *  sign-in + Drive API on the family's archive account. */

import { el, header } from "../ui.js";

export function render(main, _ctx, state) {
  main.append(header("Curator mode", state));
  main.append(
    el("div", { class: "block" }, [
      el("h3", { class: "block-title" }, "Not in the prototype"),
      el(
        "p",
        { class: "story" },
        "Curator mode is the one thing deliberately stubbed. In the real app it is a " +
          "thin client over the family archive account: Google sign-in, capture sessions (the app suggests " +
          "date+7 for weekly letters, speech-to-text for titles and story lines), batch tagging, and the " +
          "propose/confirm seam for OCR and labeling.",
      ),
      el(
        "p",
        { class: "story" },
        "The bulk path is scanners: a sheet-fed scanner for letters, a slide/photo " +
          "scanner for the trips. Scanner output lands on a laptop; tools/import (Python) uploads with " +
          "auto-naming; tagging happens here, on the phone.",
      ),
    ]),
  );
}
