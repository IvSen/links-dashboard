export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function detailOf(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).join("; ");
  } catch {
    return `ошибка ${response.status}`;
  }
  return `ошибка ${response.status}`;
}

async function request(method, path, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError("сервер не отвечает", 0);
  }
  if (!response.ok) throw new ApiError(await detailOf(response), response.status);
  return response.json();
}

function groupQuery(place) {
  const params = new URLSearchParams({ g: place.group });
  if (place.subgroup) params.set("sg", place.subgroup);
  return params.toString();
}

export const api = {
  refresh: () => request("POST", "/api/refresh"),
  snapshot: () => request("GET", "/api/snapshot"),
  group: (place) => request("GET", `/api/group?${groupQuery(place)}`),
  pinned: () => request("GET", "/api/pinned"),
  pin: (key, pinned) => request("PUT", "/api/pins", { key, pinned }),
  patchItem: (key, patch) => request("PATCH", `/api/items/${encodeURIComponent(key)}`, patch),
  putNote: (scope, text) => request("PUT", "/api/notes", { scope, text }),
  addGroup: (group, subgroup) => request("POST", "/api/groups", { group, subgroup }),
  seen: (keys) => request("POST", "/api/seen", { keys }),
  putPurpose: (name, text) => request("PUT", "/api/forward-purpose", { name, text }),
};
