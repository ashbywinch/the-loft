/** Letters — the written archive from the loft: every letter and document,
 *  in order. Told memories live elsewhere (the themes, the timeline) —
 *  this shelf is the scanned paper (user, 2026-08-03). */

import { el, header, decadeList } from "../ui.js";
import { published } from "../data.js";

export function render(main, _ctx, state) {
  const letters = published(state.items).filter((it) => it.type === "letter" || it.type === "document");
  main.append(header("Letters", state));
  main.append(
    el(
      "p",
      { class: "lede" },
      "The written archive from the loft — every letter and document, in order. Memories told here live under their themes.",
    ),
  );
  main.append(decadeList(letters, "#/timeline"));
}
