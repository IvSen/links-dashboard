from dataclasses import dataclass, field
from typing import Any

from links_dashboard.docker_source import ContainerInfo
from links_dashboard.laptop_source import LaptopInfo
from links_dashboard.mac_source import MacInfo
from links_dashboard.parsers import EdgeRoutes, Forward, SyncSession

MAC_DOWN = "Мак недоступен"
NO_DATA = "нет данных"


@dataclass(frozen=True)
class Tile:
    id: str
    title: str
    value: str
    sub: str
    bad: bool


@dataclass(frozen=True)
class Health:
    tiles: list[Tile]
    sync: list[SyncSession] = field(default_factory=list)
    forwards: list[Forward] = field(default_factory=list)
    edge: dict[str, Any] = field(default_factory=dict)
    laptop: LaptopInfo | None = None
    errors: dict[str, str] = field(default_factory=dict)


def _mac_down_tile(tile_id: str, title: str, mac_error: str | None) -> Tile:
    return Tile(tile_id, title, MAC_DOWN, mac_error or "", True)


def _no_data_tile(tile_id: str, title: str, error: str) -> Tile:
    return Tile(tile_id, title, NO_DATA, error, True)


def _sync_tile(sessions: list[SyncSession]) -> Tile:
    broken = [s.name for s in sessions if not s.ok]
    sub = ", ".join(broken) if broken else "все сессии в порядке"
    value = f"{len(sessions) - len(broken)}/{len(sessions)}"
    return Tile("sync", "Синхронизация", value, sub, bool(broken))


def _forward_label(forward: Forward, purpose: dict[str, str]) -> str:
    note = purpose.get(forward.name)
    return f"{forward.name} ({note})" if note else forward.name


def _forwards_tile(forwards: list[Forward], purpose: dict[str, str]) -> Tile:
    broken = [_forward_label(f, purpose) for f in forwards if not f.ok]
    sub = ", ".join(broken) if broken else "все пробросы работают"
    value = f"{len(forwards) - len(broken)}/{len(forwards)}"
    return Tile("forwards", "Пробросы", value, sub, bool(broken))


def _mac_tiles(mac: MacInfo | None, mac_error: str | None, purpose: dict[str, str]) -> list[Tile]:
    if mac is None:
        return [_mac_down_tile("sync", "Синхронизация", mac_error), _mac_down_tile("forwards", "Пробросы", mac_error)]
    sync_error = mac.errors.get("sync")
    forward_error = mac.errors.get("forward")
    sync = _no_data_tile("sync", "Синхронизация", sync_error) if sync_error else _sync_tile(mac.sync)
    forwards = (
        _no_data_tile("forwards", "Пробросы", forward_error)
        if forward_error
        else _forwards_tile(mac.forwards, purpose)
    )
    return [sync, forwards]


def _routing_summary(edge: EdgeRoutes) -> list[str]:
    return [
        f"HTTP :{edge.http_listen} - маршрутов: {len(edge.http)}, по умолчанию {edge.http_default}",
        f"TLS :{edge.tls_listen} - маршрутов: {len(edge.tls)}, по умолчанию {edge.tls_default}",
    ]


def _edge_details(container: ContainerInfo | None, edge: EdgeRoutes | None) -> dict[str, Any]:
    if container is None:
        return {}
    return {
        "status": "running" if container.running else "stopped",
        "running": container.running,
        "started_at": container.started_at,
        "http_listen": edge.http_listen if edge else None,
        "tls_listen": edge.tls_listen if edge else None,
        "routing": _routing_summary(edge) if edge else [],
    }


def _edge_tile(container: ContainerInfo | None, edge: EdgeRoutes | None) -> Tile:
    title = "edge-proxy"
    if container is None:
        return Tile("edge", title, "не найден", "контейнер edge-proxy отсутствует", True)
    if not container.running:
        return Tile("edge", title, "остановлен", "контейнер не запущен", True)
    sub = f"HTTP :{edge.http_listen}, TLS :{edge.tls_listen}" if edge else "конфиг недоступен"
    return Tile("edge", title, "работает", sub, edge is None)


def _laptop_tile(laptop: LaptopInfo | None) -> Tile:
    title = "Ноутбук"
    if laptop is None:
        return Tile("laptop", title, "нет данных", "источник недоступен", True)
    kind = "kind запущен" if laptop.kind_running else "kind остановлен"
    problems = []
    if not laptop.vpn:
        problems.append("VPN выключен")
    if laptop.docker_version is None:
        problems.append("Docker недоступен")
    if problems:
        return Tile("laptop", title, "проблемы", ", ".join([*problems, kind]), True)
    return Tile("laptop", title, "в порядке", f"Docker {laptop.docker_version} · VPN · {kind}", False)


def _collect_errors(mac: MacInfo | None, mac_error: str | None) -> dict[str, str]:
    errors = dict(mac.errors) if mac else {}
    if mac is None and mac_error:
        errors["mac"] = mac_error
    return errors


def build_health(
    mac: MacInfo | None,
    mac_error: str | None,
    edge_container: ContainerInfo | None,
    edge: EdgeRoutes | None,
    laptop: LaptopInfo | None,
    forward_purpose: dict[str, str],
) -> Health:
    tiles = [*_mac_tiles(mac, mac_error, forward_purpose), _edge_tile(edge_container, edge), _laptop_tile(laptop)]
    return Health(
        tiles=tiles,
        sync=list(mac.sync) if mac else [],
        forwards=list(mac.forwards) if mac else [],
        edge=_edge_details(edge_container, edge),
        laptop=laptop,
        errors=_collect_errors(mac, mac_error),
    )
