/** Museum — the heirlooms and objects: a gallery (PRD §8). */

import { el, header, itemCard } from "../ui.js";
import { published } from "../data.js";

export function render(main, _ctx, state) {
  const objects = published(state.items).filter((item) => item.type === "object");
  main.append(header("Museum", state));
  main.append(el("p", { class: "lede" }, "The things themselves — provenance narratives, no interpretation."));
  main.append(
    el(
      "div",
      { class: "card-grid" },
      objects.map((item) => itemCard(item)),
    ),
  );
}
