const URL_PATTERN = /https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]]/g;
const HOME = "/Users/i.senishin";
const SAFE_LINK = /^https?:\/\//i;

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "class") node.className = value;
    else if (name === "text") node.textContent = value;
    else if (name === "dataset") Object.assign(node.dataset, value);
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (name in node && typeof value !== "string") node[name] = value;
    else node.setAttribute(name, value === true ? "" : value);
  }
  node.append(...children.flat().filter((child) => child !== null && child !== undefined && child !== false));
  return node;
}

export function replaceChildren(target, ...children) {
  target.replaceChildren(...children.flat().filter(Boolean));
}

export function externalLink(href, text, className = "") {
  if (!SAFE_LINK.test(href)) return el("span", { text, class: className || null });
  return el("a", { href, text, class: className || null, target: "_blank", rel: "noopener" });
}

export function linkified(text) {
  const parts = [];
  let last = 0;
  for (const match of text.matchAll(URL_PATTERN)) {
    parts.push(document.createTextNode(text.slice(last, match.index)));
    parts.push(externalLink(match[0], match[0]));
    last = match.index + match[0].length;
  }
  parts.push(document.createTextNode(text.slice(last)));
  return parts;
}

export function shortPath(path) {
  if (!path) return "";
  return path.startsWith(HOME) ? `~${path.slice(HOME.length)}` : path;
}

export function formatCount(value) {
  return value === null || value === undefined ? "–" : value.toLocaleString("ru-RU");
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1000 && unit < units.length - 1) {
    size /= 1000;
    unit += 1;
  }
  const digits = size >= 10 || unit === 0 ? 0 : 1;
  return `${size.toFixed(digits).replace(".", ",")} ${units[unit]}`;
}

export function formatAgo(seconds) {
  if (seconds < 5) return "только что";
  if (seconds < 60) return `${seconds} сек назад`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} мин назад`;
  return `${Math.floor(seconds / 3600)} ч назад`;
}

export function formatUptime(startedAt) {
  const started = Date.parse(startedAt || "");
  if (Number.isNaN(started)) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - started) / 60000));
  if (minutes < 60) return `${minutes} мин`;
  if (minutes < 60 * 48) return `${Math.floor(minutes / 60)} ч`;
  return `${Math.floor(minutes / 1440)} дн`;
}

export function plural(count, one, few, many) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
