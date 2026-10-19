import { el, replaceChildren } from "./dom.js";
import { itemRow } from "./items.js";

export function renderPinned(items, ctx) {
  const box = document.getElementById("pinned");
  box.hidden = items.length === 0;
  replaceChildren(
    box,
    items.length ? el("h2", { class: "pinned__title", text: "Закреплённое" }) : null,
    items.length ? el("ul", { class: "items" }, items.map((item) => itemRow(item, ctx))) : null,
  );
}
