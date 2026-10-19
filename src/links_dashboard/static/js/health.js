import { el, formatBytes, formatCount, formatUptime, replaceChildren, shortPath } from "./dom.js";

const PURPOSE_LIMIT = 200;
const NUMERIC = new Set(["Файлы", "Конфликты", "Проблемы", "Соединений"]);

function dotClass(data) {
  if (data.bad) return "dot--down";
  return data.neutral ? "dot--na" : "dot--up";
}

function tile(data) {
  return el(
    "div",
    { class: `tile${data.bad ? " tile--bad" : ""}`, dataset: { tile: data.id } },
    el("div", { class: "tile__title" }, el("span", { class: `dot ${dotClass(data)}`, "aria-hidden": "true" }), data.title),
    el("div", { class: "tile__value", text: data.value }),
    data.sub ? el("div", { class: "tile__sub", text: data.sub }) : null,
  );
}

function table(caption, headers, rows, emptyText) {
  const body = rows.length
    ? rows
    : [el("tr", {}, el("td", { colspan: headers.length, class: "muted", text: emptyText }))];
  return el(
    "div",
    { class: "status-block" },
    el("h3", { class: "section-title", text: caption }),
    el(
      "table",
      { class: "status-table" },
      el("thead", {}, el("tr", {}, headers.map((name) => el("th", { scope: "col", text: name, class: NUMERIC.has(name) ? "num" : null })))),
      el("tbody", {}, body),
    ),
  );
}

function cell(label, content, className = "") {
  const parts = Array.isArray(content) ? content : [content];
  const value = el("span", { class: "cell__value" }, parts.map((part) => (typeof part === "string" ? document.createTextNode(part) : part)));
  return el("td", { "data-label": label, class: className || null }, value);
}

function tone(ok, warn = false) {
  if (ok) return "tone-ok";
  return warn ? "tone-warn" : "tone-err";
}

function syncRows(sessions) {
  return sessions.map((s) => {
    const size = formatBytes(s.size_bytes);
    return el(
      "tr",
      {},
      cell("Сессия", s.name, "cell-name"),
      cell("Статус", s.status_text, tone(s.ok, s.status !== "watching" && !s.problems && !s.conflicts)),
      cell("Папка на Маке", shortPath(s.path), "mono"),
      cell("Файлы", size ? `${formatCount(s.files)} · ${size}` : formatCount(s.files), "num"),
      cell("Конфликты", String(s.conflicts), s.conflicts ? "num tone-err" : "num"),
      cell("Проблемы", String(s.problems), s.problems ? "num tone-err" : "num"),
    );
  });
}

function endpointText(value) {
  return (value || "").replace(/^winbox:/, "").replace(/^tcp:/, "");
}

function purposeEditor(forward, onSavePurpose) {
  const show = (td) => {
    const text = forward.purpose || "";
    replaceChildren(
      td,
      el("button", {
        type: "button",
        class: `inline-edit${text ? "" : " inline-edit--empty"}`,
        text: text || "добавить",
        title: "Изменить, для чего этот проброс",
        onclick: () => edit(td),
      }),
    );
  };
  const edit = (td) => {
    const input = el("input", { class: "inline-input", value: forward.purpose || "", maxlength: PURPOSE_LIMIT, "aria-label": `Для чего ${forward.name}` });
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      const text = input.value.trim();
      if (!save || text === (forward.purpose || "")) return show(td);
      input.disabled = true;
      const ok = await onSavePurpose(forward.name, text);
      if (!ok) show(td);
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") finish(true);
      if (event.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
    replaceChildren(td, input);
    input.focus();
    input.select();
  };
  const td = el("td", { "data-label": "Для чего", class: "cell-purpose" });
  show(td);
  return td;
}

function forwardRows(forwards, onSavePurpose) {
  return forwards.map((f) => {
    const mac = endpointText(f.reverse ? f.destination : f.source);
    const laptop = endpointText(f.reverse ? f.source : f.destination);
    return el(
      "tr",
      {},
      cell("Имя", f.reverse ? [f.name, el("span", { class: "tag", text: "обратный" })] : f.name, "cell-name"),
      cell("Статус", f.status_text, f.configured ? "muted" : tone(f.ok)),
      cell("На Маке", mac, "mono"),
      cell("На ноутбуке", laptop, "mono"),
      cell("Соединений", f.configured ? "-" : String(f.open_connections), "num"),
      purposeEditor(f, onSavePurpose),
    );
  });
}

function edgeRows(edge) {
  if (!edge || !edge.status) return [];
  const uptime = edge.running ? formatUptime(edge.started_at) : "";
  const listen = [edge.http_listen, edge.tls_listen].filter(Boolean).join(", ");
  return [
    el(
      "tr",
      {},
      cell("Контейнер", "edge-proxy", "cell-name"),
      cell("Статус", edge.running ? `работает${uptime ? ` ${uptime}` : ""}` : "остановлен", tone(edge.running)),
      cell("Слушает", listen || "–", "mono"),
      cell("Маршруты", (edge.routing || []).flatMap((line, index) => (index ? [el("br"), line] : [line]))),
    ),
  ];
}

function laptopRows(laptop) {
  if (!laptop) return [];
  return [
    el(
      "tr",
      {},
      cell("VPN", laptop.vpn ? "подключён" : "выключен", tone(laptop.vpn)),
      cell("Docker", laptop.docker_version || "недоступен", tone(Boolean(laptop.docker_version))),
      cell("Кластер kind", laptop.kind_running ? "запущен" : "остановлен", tone(laptop.kind_running, true)),
    ),
  ];
}

function noteBlock(note) {
  return note ? el("p", { class: "muted", text: note }) : null;
}

function errorsBlock(errors) {
  const entries = Object.entries(errors || {});
  if (!entries.length) return null;
  return el(
    "div",
    { class: "status-block" },
    el("h3", { class: "section-title", text: "Ошибки при сборе данных" }),
    el("ul", { class: "error-list" }, entries.map(([name, text]) => el("li", {}, el("b", { text: name }), ` ${text}`))),
  );
}

export function renderHealth(health, onSavePurpose) {
  replaceChildren(document.getElementById("tiles"), health.tiles.map(tile));
  const macDown = "нет данных с Мака";
  replaceChildren(
    document.getElementById("health-body"),
    table("Синхронизация Mutagen", ["Сессия", "Статус", "Папка на Маке", "Файлы", "Конфликты", "Проблемы"], syncRows(health.sync), macDown),
    table("Пробросы портов", ["Имя", "Статус", "На Маке", "На ноутбуке", "Соединений", "Для чего"], forwardRows(health.forwards, onSavePurpose), macDown),
    table("edge-proxy", ["Контейнер", "Статус", "Слушает", "Маршруты"], edgeRows(health.edge), "контейнер edge-proxy не найден"),
    table("Ноутбук", ["VPN", "Docker", "Кластер kind"], laptopRows(health.laptop), "нет данных"),
    noteBlock(health.mac_note),
    errorsBlock(health.errors),
  );
}
