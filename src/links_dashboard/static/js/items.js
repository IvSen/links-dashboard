import { el, externalLink, replaceChildren } from "./dom.js";
import { placeFromId, placeId, placeLabel, placeOf } from "./places.js";

const NAME_LIMIT = 200;
const TEXT_LIMIT = 20000;
const COPIED_MS = 1500;
const STATUS = {
  up: { dot: "dot--up", text: "отвечает" },
  down: { dot: "dot--down", text: "не отвечает" },
  na: { dot: "dot--na", text: "недоступен с Мака" },
  missing: { dot: "dot--missing", text: "пропал из источников" },
};
const SOURCES = { hosts: "hosts Мака", cluster: "кластер" };

function sourceText(item) {
  if (item.source === "container") return item.details.container ? `контейнер ${item.details.container}` : "контейнер";
  return SOURCES[item.source] || item.source;
}

function copyButton(item) {
  const value = item.kind === "web" && item.url ? item.url : item.details.address || item.label;
  const button = el("button", { type: "button", class: "link-button", text: "копировать", title: `Скопировать ${value}` });
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(value);
      button.textContent = "скопировано";
    } catch {
      button.textContent = "не удалось";
    }
    setTimeout(() => { button.textContent = "копировать"; }, COPIED_MS);
  });
  return button;
}

function address(item) {
  if (item.kind === "web" && item.url) return externalLink(item.url, item.url, "item__address item__address--link");
  return el("span", { class: "item__address", text: item.label });
}

function statusNote(item) {
  if (item.status === "up") return null;
  return el("span", { class: `item__status item__status--${item.status}`, text: STATUS[item.status].text });
}

function badges(item) {
  return [
    item.is_new ? el("span", { class: "badge badge--new", text: "новое" }) : null,
    item.login_hint ? el("span", { class: "tag tag--hint", text: item.login_hint }) : null,
    el("span", { class: "tag tag--source", text: sourceText(item) }),
    item.cached ? el("span", { class: "tag tag--source", text: "по старым данным", title: "Мак не ответил, список hosts из прошлой проверки" }) : null,
  ];
}

function placeSelect(places, current, { includeEmpty, label }) {
  const options = places.map((place) => el("option", { value: placeId(place), text: placeLabel(place), selected: current && placeId(place) === placeId(current) }));
  const prompt = includeEmpty ? [el("option", { value: "", text: label, selected: true, disabled: true })] : [];
  return el("select", { class: "select", "aria-label": label }, prompt, options);
}

function placePatch(id) {
  const place = placeFromId(id);
  return { group: place.group, subgroup: place.subgroup };
}

function moveSelect(item, ctx) {
  const targets = ctx.places.filter((place) => place.group);
  const select = placeSelect(targets, null, { includeEmpty: true, label: "в группу…" });
  select.classList.add("select--compact");
  select.addEventListener("change", () => ctx.onPatch(item.key, placePatch(select.value)));
  return select;
}

function field(label, control, extraClass = "") {
  return el("label", { class: `field ${extraClass}`.trim() }, el("span", { class: "field__label", text: label }), control);
}

function nullable(value) {
  const text = value.trim();
  return text ? text : null;
}

function editForm(item, ctx, close) {
  const title = el("input", { value: item.title || "", maxlength: NAME_LIMIT, placeholder: item.label });
  const description = el("textarea", { rows: 2, maxlength: TEXT_LIMIT }, item.description || "");
  const hint = el("input", { value: item.login_hint || "", maxlength: NAME_LIMIT, placeholder: "например: логин в заметке" });
  const place = placeSelect(ctx.places, placeOf(item.group, item.subgroup), { includeEmpty: false, label: "Группа / подгруппа" });
  const kind = el("select", { class: "select" },
    el("option", { value: "web", text: "открыть в браузере", selected: item.kind === "web" }),
    el("option", { value: "conn", text: "подключение", selected: item.kind === "conn" }),
  );
  const submit = el("button", { type: "submit", class: "btn btn--primary btn--small", text: "Сохранить" });
  const form = el(
    "form",
    {
      class: "edit-form",
      onsubmit: async (event) => {
        event.preventDefault();
        submit.disabled = true;
        const ok = await ctx.onPatch(item.key, {
          title: nullable(title.value),
          description: nullable(description.value),
          login_hint: nullable(hint.value),
          ...placePatch(place.value),
          kind: kind.value,
        });
        if (!ok) submit.disabled = false;
      },
      onkeydown: (event) => event.key === "Escape" && close(),
    },
    el("div", { class: "edit-form__grid" },
      field("Название", title),
      field("Подсказка для входа", hint),
      field("Описание", description, "field--wide"),
      field("Группа / подгруппа", place),
      field("Тип", kind),
    ),
    el("div", { class: "form__actions" },
      submit,
      el("button", { type: "button", class: "btn btn--ghost btn--small", text: "Отмена", onclick: close }),
    ),
  );
  setTimeout(() => title.focus(), 0);
  return form;
}

function actions(item, ctx, row) {
  if (ctx.mode === "search") return [item.kind === "conn" ? copyButton(item) : null];
  if (ctx.mode === "hidden") {
    return [el("button", { type: "button", class: "link-button", text: "вернуть", onclick: () => ctx.onPatch(item.key, { hidden: false }) })];
  }
  const slot = row.querySelector(".item__editor");
  const close = () => replaceChildren(slot);
  return [
    !item.group ? moveSelect(item, ctx) : null,
    item.kind === "conn" ? copyButton(item) : null,
    el("button", { type: "button", class: "link-button", text: "изменить", onclick: () => replaceChildren(slot, editForm(item, ctx, close)) }),
    el("button", { type: "button", class: "link-button", text: "скрыть", onclick: () => ctx.onPatch(item.key, { hidden: true }) }),
  ];
}

export function itemRow(item, ctx) {
  const status = STATUS[item.status] || STATUS.down;
  const dim = item.status === "down" || item.status === "missing";
  const row = el("li", { class: `item${dim ? " item--dim" : ""}`, dataset: { key: item.key } });
  const line = el(
    "div",
    { class: "item__line" },
    el("span", { class: `dot ${status.dot}`, title: status.text, role: "img", "aria-label": status.text }),
    el(
      "div",
      { class: "item__main" },
      el("div", { class: "item__head" }, item.title ? el("span", { class: "item__title", text: item.title }) : null, address(item), statusNote(item), badges(item)),
      item.description ? el("div", { class: "item__desc", text: item.description }) : null,
    ),
  );
  const editor = el("div", { class: "item__editor" });
  row.append(line, editor);
  line.append(el("div", { class: "item__actions" }, actions(item, ctx, row)));
  return row;
}

export function itemSections(items, ctx) {
  const web = items.filter((item) => item.kind === "web");
  const conn = items.filter((item) => item.kind !== "web");
  return [
    web.length ? el("h3", { class: "section-title", text: "Открыть в браузере" }) : null,
    web.length ? el("ul", { class: "items" }, web.map((item) => itemRow(item, ctx))) : null,
    conn.length ? el("h3", { class: "section-title", text: "Подключения" }) : null,
    conn.length ? el("ul", { class: "items" }, conn.map((item) => itemRow(item, ctx))) : null,
  ];
}
