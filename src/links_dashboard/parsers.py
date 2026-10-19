import re
from dataclasses import dataclass

import yaml

HOSTS_LOOPBACK = "127.0.0.1"
HOSTS_EXCLUDED = frozenset({"localhost", "broadcasthost", "kubernetes.docker.internal"})

SYNC_STATUS_TEXT = {
    "watching": "следит за изменениями",
    "scanning": "сканирует",
    "staging-alpha": "передаёт файлы",
    "staging-beta": "передаёт файлы",
    "transitioning": "передаёт файлы",
    "saving": "передаёт файлы",
}
NO_LINK_TEXT = "нет связи"
PAUSED_TEXT = "на паузе"
FORWARDING_TEXT = "работает"
CONFIGURED_TEXT = "из конфига"
CONFIGURED_STATUS = "configured"
FORWARD_DEFAULTS_KEY = "defaults"

_ENDPOINT_PORT = re.compile(r"^tcp\d?:.*:(\d+)$")
_FORWARD_URL = re.compile(r"^(?:(?P<host>.+?):)?(?P<endpoint>(?:tcp[46]?|unix|npipe):.*)$")
_LISTEN = re.compile(r"^\s*listen\s+(\d+)\b", re.MULTILINE)
_MAP_ENTRY = re.compile(r"^\s*(\S+)\s+[\w.\-]+:(\d+)\s*;", re.MULTILINE)


def parse_hosts(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) < 2 or fields[0] != HOSTS_LOOPBACK:
            continue
        for raw in fields[1:]:
            name = raw.strip(",").lower()
            if name and name not in HOSTS_EXCLUDED:
                seen.setdefault(name)
    return list(seen)


@dataclass(frozen=True)
class SyncSession:
    name: str
    status: str
    status_text: str
    path: str
    files: int | None
    size_bytes: int | None
    conflicts: int
    problems: int
    paused: bool
    ok: bool


def _sync_status_text(status: str, paused: bool) -> str:
    if paused:
        return PAUSED_TEXT
    if status in SYNC_STATUS_TEXT:
        return SYNC_STATUS_TEXT[status]
    return NO_LINK_TEXT if status.startswith("connecting") or status == "disconnected" else status


def _count_problems(raw: dict) -> int:
    alpha = raw.get("alpha") or {}
    beta = raw.get("beta") or {}
    return (
        len(alpha.get("scanProblems") or [])
        + len(beta.get("scanProblems") or [])
        + len(raw.get("transitionProblems") or [])
    )


def _parse_session(raw: dict) -> SyncSession:
    alpha = raw.get("alpha") or {}
    status = str(raw.get("status", ""))
    paused = bool(raw.get("paused", False))
    conflicts = len(raw.get("conflicts") or [])
    problems = _count_problems(raw)
    return SyncSession(
        name=str(raw.get("name", "")),
        status=status,
        status_text=_sync_status_text(status, paused),
        path=str(alpha.get("path", "")),
        files=alpha.get("files"),
        size_bytes=alpha.get("totalFileSize"),
        conflicts=conflicts,
        problems=problems,
        paused=paused,
        ok=status == "watching" and not conflicts and not problems and not paused,
    )


def parse_sync(data: list[dict]) -> list[SyncSession]:
    return [_parse_session(raw) for raw in data]


@dataclass(frozen=True)
class Forward:
    name: str
    ok: bool
    status_text: str
    source: str
    destination: str
    dest_port: int | None
    src_port: int | None
    reverse: bool
    open_connections: int
    configured: bool = False


def _forward_url(side: dict) -> str:
    endpoint = str(side.get("endpoint", ""))
    host = side.get("host")
    return f"{host}:{endpoint}" if host else endpoint


def _endpoint_port(side: dict) -> int | None:
    match = _ENDPOINT_PORT.match(str(side.get("endpoint", "")))
    return int(match.group(1)) if match else None


def _forward_status_text(status: str, paused: bool) -> str:
    if paused:
        return PAUSED_TEXT
    if status == "forwarding":
        return FORWARDING_TEXT
    if status == CONFIGURED_STATUS:
        return CONFIGURED_TEXT
    return NO_LINK_TEXT if status.startswith("connecting") or status == "disconnected" else status


def _parse_forward(raw: dict) -> Forward:
    source = raw.get("source") or {}
    destination = raw.get("destination") or {}
    status = str(raw.get("status", ""))
    paused = bool(raw.get("paused", False))
    return Forward(
        name=str(raw.get("name", "")),
        ok=status == "forwarding" and not paused,
        status_text=_forward_status_text(status, paused),
        source=_forward_url(source),
        destination=_forward_url(destination),
        dest_port=_endpoint_port(destination),
        src_port=_endpoint_port(source),
        reverse=_forward_url(source).startswith("winbox:"),
        open_connections=int(raw.get("openConnections") or 0),
        configured=status == CONFIGURED_STATUS,
    )


def parse_forwards(data: list[dict]) -> list[Forward]:
    return [_parse_forward(raw) for raw in data]


def _split_forward_url(url: object, name: str) -> dict:
    match = _FORWARD_URL.match(url) if isinstance(url, str) else None
    if match is None:
        raise ValueError(f"forward {name}: unsupported endpoint {url!r}")
    side = {"endpoint": match.group("endpoint")}
    return {**side, "host": match.group("host")} if match.group("host") else side


def _config_forward(name: str, spec: object) -> Forward:
    if not isinstance(spec, dict):
        raise ValueError(f"forward {name} must be a mapping")
    return _parse_forward(
        {
            "name": name,
            "status": CONFIGURED_STATUS,
            "source": _split_forward_url(spec.get("source"), name),
            "destination": _split_forward_url(spec.get("destination"), name),
        }
    )


def parse_forward_config(text: str) -> list[Forward]:
    """Forwards declared in the `forward:` section of a Mutagen project file, without live status."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid Mutagen project file: {error}") from error
    if data is None:
        return []
    if not isinstance(data, dict):
        raise ValueError("Mutagen project file must be a mapping")
    section = data.get("forward") or {}
    if not isinstance(section, dict):
        raise ValueError("forward section must be a mapping")
    return [_config_forward(str(name), spec) for name, spec in section.items() if name != FORWARD_DEFAULTS_KEY]


Route = tuple[str, bool, int]


@dataclass(frozen=True)
class EdgeRoutes:
    http_listen: int
    tls_listen: int
    http: list[Route]
    tls: list[Route]
    http_default: int
    tls_default: int

    def route_http(self, host: str) -> int:
        return _route(self.http, self.http_default, host)

    def route_tls(self, host: str) -> int:
        return _route(self.tls, self.tls_default, host)


def _route(routes: list[Route], default: int, host: str) -> int:
    name = host.lower()
    for pattern, is_regex, port in routes:
        if not is_regex and pattern.lower() == name:
            return port
    for pattern, is_regex, port in routes:
        if is_regex and re.search(pattern, name):
            return port
    return default


def _block_body(text: str, header: str) -> str:
    match = re.search(header, text, re.MULTILINE)
    if match is None:
        raise ValueError(f"edge config block not found: {header}")
    start = match.end()
    depth = 1
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
    raise ValueError(f"edge config block not closed: {header}")


def _parse_map(body: str) -> tuple[list[Route], int]:
    routes: list[Route] = []
    default: int | None = None
    for pattern, port in _MAP_ENTRY.findall(body):
        if pattern == "default":
            default = int(port)
        elif pattern.startswith("~*"):
            routes.append((pattern[2:], True, int(port)))
        elif pattern.startswith("~"):
            routes.append((pattern[1:], True, int(port)))
        else:
            routes.append((pattern, False, int(port)))
    if default is None:
        raise ValueError("edge config map has no default")
    return routes, default


def _listen_port(body: str, name: str) -> int:
    match = _LISTEN.search(body)
    if match is None:
        raise ValueError(f"edge config has no listen in {name} block")
    return int(match.group(1))


def parse_edge_conf(text: str) -> EdgeRoutes:
    stream = _block_body(text, r"^\s*stream\s*\{")
    http = _block_body(text, r"^\s*http\s*\{")
    tls_map = _block_body(stream, r"map\s+\$ssl_preread_server_name\s+\$tls_upstream\s*\{")
    http_map = _block_body(http, r"map\s+\$host\s+\$http_upstream\s*\{")
    tls_routes, tls_default = _parse_map(tls_map)
    http_routes, http_default = _parse_map(http_map)
    return EdgeRoutes(
        http_listen=_listen_port(http, "http"),
        tls_listen=_listen_port(stream, "stream"),
        http=http_routes,
        tls=tls_routes,
        http_default=http_default,
        tls_default=tls_default,
    )
