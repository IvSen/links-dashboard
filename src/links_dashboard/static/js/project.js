import { el, linkified, replaceChildren, shortPath } from "./dom.js";
import { itemRow, itemSections } from "./items.js";
import { NO_GROUP_LABEL, placeLabel } from "./places.js";

const TEXT_LIMIT = 20000;

function heading(place) {
  if (!place.group) return el("h2", { class: "project__title", text: NO_GROUP_LABEL });
  return el(
    "h2",
    { class: "project__title" },
    place.subgroup ? el("span", { class: "project__parent", text: `${place.group} /` }) : null,
    place.subgroup || place.group,
  );
}

function containersText(project) {
  const stopped = project.stopped.length ? ` · остановлен ${project.stopped.join(", ")}` : "";
  return `контейнеры ${project.running} из ${project.total}${stopped}`;
}

function meta(project) {
  if (!project) return null;
  return el(
    "div",
    { class: "project__meta" },
    el("span", {}, "папка ", el("code", { text: shortPath(project.folder) })),
    project.branch ? el("span", {}, "ветка ", el("code", { text: project.branch })) : null,
    el("span", { class: project.running < project.total ? "tone-warn" : "", text: containersText(project) }),
  );
}

function noteView(slot, text, onSaveNote) {
  const editButton = el("button", {
    type: "button",
    class: "link-button note__edit",
    text: text ? "изменить" : "добавить заметку",
    onclick: () => noteEditor(slot, text, onSaveNote),
  });
  const body = text ? el("div", { class: "note__text" }, linkified(text)) : el("div", { class: "note__text muted", text: "Заметки нет. Сюда удобно записать тестовых пользователей и пароли." });
  replaceChildren(slot, el("div", { class: `note${text ? "" : " note--empty"}` }, editButton, body));
}

function noteEditor(slot, text, onSaveNote) {
  const area = el("textarea", { class: "note__input", rows: Math.max(4, text.split("\n").length + 1), maxlength: TEXT_LIMIT, "aria-label": "Заметка" }, text);
  const save = el("button", { type: "submit", class: "btn btn--primary btn--small", text: "Сохранить" });
  const cancel = () => noteView(slot, text, onSaveNote);
  const form = el(
    "form",
    {
      class: "note note--editing",
      onsubmit: async (event) => {
        event.preventDefault();
        save.disabled = true;
        const saved = await onSaveNote(area.value);
        if (saved === null) save.disabled = false;
        else noteView(slot, saved, onSaveNote);
      },
      onkeydown: (event) => event.key === "Escape" && cancel(),
    },
    area,
    el("div", { class: "form__actions" }, save, el("button", { type: "button", class: "btn btn--ghost btn--small", text: "Отмена", onclick: cancel })),
  );
  replaceChildren(slot, form);
  area.focus();
}

function emptyItems(place) {
  const text = place.group
    ? "Здесь пока нет адресов. Новые появятся сами, когда их найдёт проверка."
    : "Все найденные адреса разложены по группам.";
  return el("p", { class: "empty", text });
}

function hiddenList(hidden, ctx) {
  if (!hidden.length) return null;
  return el(
    "details",
    { class: "hidden-list" },
    el("summary", { text: `Скрытые (${hidden.length})` }),
    el("ul", { class: "items" }, hidden.map((item) => itemRow(item, { ...ctx, mode: "hidden" }))),
  );
}

export function renderProjectLoading(place) {
  replaceChildren(
    document.getElementById("project"),
    heading(place),
    el("div", { class: "skeleton", "aria-label": "Загрузка" }, el("span"), el("span"), el("span"), el("span")),
  );
}

export function renderProjectError(place, message, onRetry) {
  replaceChildren(
    document.getElementById("project"),
    heading(place),
    el("p", { class: "empty tone-err", text: `Не удалось загрузить группу: ${message}` }),
    el("button", { type: "button", class: "btn btn--small", text: "Повторить", onclick: onRetry }),
  );
}

export function renderProject(place, view, ctx) {
  const noteSlot = el("div", { class: "note-slot" });
  noteView(noteSlot, view.note || "", ctx.onSaveNote);
  replaceChildren(
    document.getElementById("project"),
    el("header", { class: "project__header" }, heading(place), meta(view.project)),
    !place.group ? el("p", { class: "muted project__hint", text: "Адреса, для которых не удалось определить группу. Разложите их через «в группу…»." }) : null,
    noteSlot,
    view.items.length ? itemSections(view.items, { ...ctx, mode: "full" }) : emptyItems(place),
    hiddenList(view.hidden, ctx),
  );
}

export function renderSearch(query, results, onOpen) {
  const total = results.reduce((sum, entry) => sum + entry.items.length, 0);
  const sections = results.map((entry) =>
    el(
      "section",
      { class: "search-group" },
      el("h3", { class: "search-group__title" }, el("button", { type: "button", class: "link-button", text: placeLabel(entry.place), onclick: () => onOpen(entry.place) })),
      el("ul", { class: "items" }, entry.items.map((item) => itemRow(item, { mode: "search", places: [] }))),
    ),
  );
  replaceChildren(
    document.getElementById("project"),
    el("header", { class: "project__header" }, el("h2", { class: "project__title", text: total ? `Найдено: ${total}` : "Ничего не найдено" }), el("div", { class: "project__meta" }, el("span", { text: `по запросу «${query}»` }))),
    sections,
  );
}
