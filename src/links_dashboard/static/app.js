import { api } from "./js/api.js";
import { el, formatAgo, replaceChildren } from "./js/dom.js";
import { renderHealth } from "./js/health.js";
import { renderPinned } from "./js/pinned.js";
import { initialPlace, noteScope, placeId, placeOf, samePlace, selectablePlaces } from "./js/places.js";
import { renderLoadFailure, renderProject, renderProjectError, renderProjectLoading, renderSearch } from "./js/project.js";
import { renderTree } from "./js/tree.js";

const STORAGE_KEY = "links-dashboard.place";
const SEARCH_DELAY_MS = 200;
const NOTICE_MS = 6000;
const SOURCE_NAMES = { mac: "Мак", docker: "Docker", cluster: "кластер", edge: "конфиг edge-proxy", laptop: "ноутбук" };

let state = Object.freeze({ snapshot: null, receivedAt: null, selected: null, view: null, cache: {}, query: "", refreshing: false });
let loadToken = 0;
let pinnedToken = 0;
let searchTimer = null;
let noticeTimer = null;

function setState(patch) {
  state = Object.freeze({ ...state, ...patch });
}

function recalled() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    return saved && typeof saved.group === "string" ? placeOf(saved.group, saved.subgroup) : null;
  } catch {
    return null;
  }
}

function remember(place) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(place));
  } catch {
    return;
  }
}

function notify(message) {
  const box = document.getElementById("notice");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { box.hidden = true; }, NOTICE_MS);
}

function renderFailed(failed) {
  const banner = document.getElementById("failed");
  const parts = Object.entries(failed || {}).map(([name, reason]) => `${SOURCE_NAMES[name] || name} (${reason})`);
  banner.hidden = parts.length === 0;
  replaceChildren(banner, parts.length ? el("span", { text: `Не удалось получить данные: ${parts.join("; ")}` }) : null);
}

function tickAgo() {
  const label = document.getElementById("checked-ago");
  if (state.refreshing) label.textContent = "проверяю…";
  else if (state.receivedAt) label.textContent = `проверено ${formatAgo(Math.floor((Date.now() - state.receivedAt) / 1000))}`;
}

function renderSidebar() {
  renderTree({ nodes: state.snapshot.tree, selected: state.selected, onSelect: selectGroup, onAddGroup: addGroup, keepForm: true });
}

function applySnapshot(snapshot, fresh) {
  setState({ snapshot, cache: {}, ...(fresh ? { receivedAt: Date.now() } : {}) });
  renderFailed(snapshot.failed_sources);
  renderHealth(snapshot.health, savePurpose);
  renderSidebar();
  tickAgo();
}

function withoutNew(tree, place) {
  return tree.map((node) => (samePlace(placeOf(node.group, node.subgroup), place) ? { ...node, new_count: 0 } : node));
}

async function markSeen(place, view) {
  const keys = view.items.filter((item) => item.is_new).map((item) => item.key);
  if (!keys.length) return;
  try {
    await api.seen(keys);
    setState({ snapshot: { ...state.snapshot, tree: withoutNew(state.snapshot.tree, place) } });
    renderSidebar();
  } catch (error) {
    notify(`Не удалось отметить новое как просмотренное: ${error.message}`);
  }
}

function projectContext() {
  return { places: selectablePlaces(state.snapshot.tree), onPatch: patchItem, onSaveNote: saveNote, onPin: setPin };
}

async function loadPinned() {
  const token = ++pinnedToken;
  try {
    const { items } = await api.pinned();
    if (token !== pinnedToken) return;
    renderPinned(items, { mode: "pinned", places: [], onPin: setPin });
  } catch (error) {
    notify(`Не удалось загрузить закреплённое: ${error.message}`);
  }
}

async function loadGroup(place) {
  const token = ++loadToken;
  if (!state.query) renderProjectLoading(place);
  try {
    const view = await api.group(place);
    if (token !== loadToken) return;
    setState({ view, cache: { ...state.cache, [placeId(place)]: view } });
    if (!state.query) renderProject(place, view, projectContext());
    await markSeen(place, view);
  } catch (error) {
    if (token === loadToken) renderProjectError(place, error.message, () => loadGroup(place));
  }
}

function selectGroup(place) {
  const input = document.getElementById("search");
  if (input.value) input.value = "";
  setState({ selected: place, query: "" });
  remember(place);
  renderSidebar();
  return loadGroup(place);
}

async function reloadAfterWrite() {
  applySnapshot(await api.snapshot(), false);
  await Promise.all([loadGroup(state.selected), loadPinned()]);
}

async function write(action, failure) {
  try {
    await action();
    return true;
  } catch (error) {
    notify(`${failure}: ${error.message}`);
    return false;
  }
}

function patchItem(key, patch) {
  return write(async () => {
    await api.patchItem(key, patch);
    await reloadAfterWrite();
  }, "Не удалось сохранить адрес");
}

function setPin(key, pinned) {
  return write(async () => {
    await api.pin(key, pinned);
    await reloadAfterWrite();
    if (state.query) await runSearch(state.query);
  }, pinned ? "Не удалось закрепить адрес" : "Не удалось открепить адрес");
}

function withNote(place, text) {
  const key = placeId(place);
  const view = state.view ? { ...state.view, note: text } : null;
  const cached = state.cache[key] ? { ...state.cache, [key]: { ...state.cache[key], note: text } } : state.cache;
  return { view, cache: cached };
}

async function saveNote(text) {
  const place = state.selected;
  const ok = await write(() => api.putNote(noteScope(place), text), "Не удалось сохранить заметку");
  if (!ok) return null;
  if (samePlace(place, state.selected)) setState(withNote(place, text));
  return text;
}

function addGroup(group, subgroup) {
  return write(async () => {
    await api.addGroup(group, subgroup);
    applySnapshot(await api.snapshot(), false);
  }, "Не удалось добавить группу");
}

function savePurpose(name, text) {
  return write(async () => {
    await api.putPurpose(name, text);
    applySnapshot(await api.snapshot(), false);
  }, "Не удалось сохранить описание проброса");
}

function setRefreshing(refreshing) {
  setState({ refreshing });
  const button = document.getElementById("refresh");
  button.disabled = refreshing;
  button.classList.toggle("is-busy", refreshing);
  button.querySelector(".btn__label").textContent = refreshing ? "Обновляю…" : "Обновить";
  tickAgo();
}

function showLoadFailure(message) {
  renderLoadFailure(message, refresh);
  document.getElementById("checked-ago").textContent = "не удалось проверить";
}

async function refresh() {
  if (state.refreshing) return;
  setRefreshing(true);
  try {
    const snapshot = await api.refresh();
    const selected = initialPlace(snapshot.tree, state.selected || recalled());
    setState({ selected });
    applySnapshot(snapshot, true);
    await Promise.all([loadGroup(selected), loadPinned()]);
    if (state.query) await runSearch(state.query);
  } catch (error) {
    if (state.snapshot) notify(`Не удалось обновить: ${error.message}`);
    else showLoadFailure(error.message);
  } finally {
    setRefreshing(false);
  }
}

function matches(item, needle) {
  return [item.label, item.url, item.title, item.description].some((text) => (text || "").toLowerCase().includes(needle));
}

async function allViews() {
  const places = state.snapshot.tree.filter((node) => node.count > 0).map((node) => placeOf(node.group, node.subgroup));
  const missing = places.filter((place) => !state.cache[placeId(place)]);
  const loaded = await Promise.all(missing.map(async (place) => [placeId(place), await api.group(place)]));
  setState({ cache: { ...state.cache, ...Object.fromEntries(loaded) } });
  return places.map((place) => ({ place, view: state.cache[placeId(place)] }));
}

async function runSearch(query) {
  const needle = query.toLowerCase();
  try {
    const views = await allViews();
    if (state.query !== query) return;
    const results = views
      .map(({ place, view }) => ({ place, items: view.items.filter((item) => matches(item, needle)) }))
      .filter((entry) => entry.items.length);
    renderSearch(query, results, selectGroup);
  } catch (error) {
    notify(`Поиск не удался: ${error.message}`);
  }
}

function onSearchInput(event) {
  const query = event.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    setState({ query });
    if (!state.snapshot) return;
    if (query) runSearch(query);
    else if (state.view) renderProject(state.selected, state.view, projectContext());
  }, SEARCH_DELAY_MS);
}

function start() {
  document.getElementById("refresh").addEventListener("click", refresh);
  const search = document.getElementById("search");
  search.addEventListener("input", onSearchInput);
  search.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && search.value) {
      search.value = "";
      search.dispatchEvent(new Event("input"));
    }
  });
  setInterval(tickAgo, 1000);
  refresh();
}

start();
