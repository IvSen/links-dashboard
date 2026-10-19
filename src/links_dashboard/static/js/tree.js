import { el, plural, replaceChildren } from "./dom.js";
import {
  NO_GROUP_LABEL,
  groupedTree,
  placeFromId,
  placeId,
  placeLabel,
  placeOf,
  samePlace,
} from "./places.js";

const NAME_LIMIT = 200;

function newBadge(count) {
  return count > 0 ? el("span", { class: "badge badge--new", text: String(count), title: "новых" }) : null;
}

function nodeButton(label, node, place, selected, onSelect, extraClass = "") {
  const active = samePlace(place, selected);
  return el(
    "button",
    {
      type: "button",
      class: `tree__node ${extraClass}${active ? " is-active" : ""}`,
      "aria-current": active ? "true" : null,
      onclick: () => onSelect(place),
    },
    el("span", { class: "tree__name", text: label }),
    el("span", { class: "tree__count", text: String(node.count) }),
    newBadge(node.new_count),
  );
}

function groupHead(entry, selected, onSelect) {
  if (!entry.group) {
    const orphan = entry.count > 0 ? " tree__node--orphan" : " tree__node--empty";
    return nodeButton(NO_GROUP_LABEL, entry.own, placeOf("", null), selected, onSelect, orphan.trim());
  }
  if (entry.own) {
    const merged = { count: entry.count, new_count: entry.newCount };
    return nodeButton(entry.group, merged, placeOf(entry.group, null), selected, onSelect, "tree__node--head");
  }
  return el(
    "div",
    { class: "tree__label" },
    el("span", { class: "tree__name", text: entry.group }),
    el("span", { class: "tree__count", text: String(entry.count) }),
    newBadge(entry.newCount),
  );
}

function treeList(nodes, selected, onSelect) {
  return groupedTree(nodes).map((entry) =>
    el(
      "li",
      { class: "tree__group" },
      groupHead(entry, selected, onSelect),
      entry.subgroups.length
        ? el(
            "ul",
            { class: "tree__subs" },
            entry.subgroups.map((node) =>
              el("li", {}, nodeButton(node.subgroup, node, placeOf(node.group, node.subgroup), selected, onSelect, "tree__node--sub")),
            ),
          )
        : null,
    ),
  );
}

function optionText(node) {
  const place = placeOf(node.group, node.subgroup);
  const fresh = node.new_count > 0 ? ` · ${node.new_count} ${plural(node.new_count, "новый", "новых", "новых")}` : "";
  return `${placeLabel(place)} · ${node.count}${fresh}`;
}

function fillSelect(select, nodes, selected, onSelect) {
  const ordered = groupedTree(nodes).flatMap((entry) => [entry.own, ...entry.subgroups].filter(Boolean));
  const options = ordered.map((node) => {
    const place = placeOf(node.group, node.subgroup);
    return el("option", { value: placeId(place), text: optionText(node), selected: samePlace(place, selected) });
  });
  replaceChildren(select, options);
  select.onchange = () => onSelect(placeFromId(select.value));
}

function addGroupForm(container, nodes, onAddGroup) {
  const groupInput = el("input", { name: "group", required: true, maxlength: NAME_LIMIT, placeholder: "группа", list: "known-groups" });
  const subInput = el("input", { name: "subgroup", maxlength: NAME_LIMIT, placeholder: "подгруппа (не обязательно)" });
  const known = [...new Set(nodes.map((node) => node.group).filter(Boolean))];
  const close = () => renderAddGroup(container, nodes, onAddGroup);
  const form = el(
    "form",
    {
      class: "add-group",
      onsubmit: async (event) => {
        event.preventDefault();
        const group = groupInput.value.trim();
        if (!group) return groupInput.focus();
        const ok = await onAddGroup(group, subInput.value.trim() || null);
        if (ok) close();
      },
      onkeydown: (event) => event.key === "Escape" && close(),
    },
    el("datalist", { id: "known-groups" }, known.map((name) => el("option", { value: name }))),
    groupInput,
    subInput,
    el("div", { class: "form__actions" },
      el("button", { type: "submit", class: "btn btn--primary btn--small", text: "Добавить" }),
      el("button", { type: "button", class: "btn btn--ghost btn--small", text: "Отмена", onclick: close }),
    ),
  );
  replaceChildren(container, form);
  groupInput.focus();
}

function renderAddGroup(container, nodes, onAddGroup) {
  replaceChildren(
    container,
    el("button", {
      type: "button",
      class: "link-button tree__add-button",
      text: "+ группа / подгруппа",
      onclick: () => addGroupForm(container, nodes, onAddGroup),
    }),
  );
}

export function renderTree({ nodes, selected, onSelect, onAddGroup, keepForm = false }) {
  replaceChildren(document.getElementById("tree-list"), treeList(nodes, selected, onSelect));
  fillSelect(document.getElementById("group-select"), nodes, selected, onSelect);
  const add = document.getElementById("tree-add");
  if (!keepForm || !add.querySelector("form")) renderAddGroup(add, nodes, onAddGroup);
}
