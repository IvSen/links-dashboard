from links_dashboard.docker_source import ContainerInfo
from links_dashboard.health import build_health
from links_dashboard.laptop_source import LaptopInfo
from links_dashboard.mac_source import MacInfo
from links_dashboard.parsers import EdgeRoutes, Forward, SyncSession


def session(name: str = "app", ok: bool = True) -> SyncSession:
    return SyncSession(name, "watching", "Watching", "/p", 10, 100, 0, 0, False, ok)


def forward(name: str = "db", ok: bool = True) -> Forward:
    return Forward(name, ok, "Connected", "tcp:a", "tcp:b", 5432, 15432, False, 0)


EDGE = EdgeRoutes(
    http_listen=80,
    tls_listen=443,
    http=[("a.test", False, 8001)],
    tls=[("a.test", False, 8443), ("b.test", False, 8444)],
    http_default=8000,
    tls_default=8442,
)
CONTAINER = ContainerInfo("edge-proxy", True, "nginx", "2026-10-19T10:00:00Z", None, None)
LAPTOP = LaptopInfo(vpn=True, docker_version="27.0", kind_running=True)


def test_mac_down_tiles():
    health = build_health(None, "timeout", CONTAINER, EDGE, LAPTOP, {})
    assert [t.id for t in health.tiles] == ["sync", "forwards", "edge", "laptop"]
    assert [t.title for t in health.tiles] == ["Синхронизация", "Пробросы", "edge-proxy", "Ноутбук"]
    for tile in health.tiles[:2]:
        assert tile.value == "Мак недоступен"
        assert tile.bad is True
        assert tile.sub == "timeout"
    assert health.tiles[2].bad is False
    assert health.tiles[3].bad is False
    assert health.errors["mac"] == "timeout"


def test_all_good():
    mac = MacInfo(sync=[session()], forwards=[forward()])
    health = build_health(mac, None, CONTAINER, EDGE, LAPTOP, {})
    assert [t.bad for t in health.tiles] == [False, False, False, False]
    assert health.tiles[0].value == "1/1"
    assert health.tiles[1].value == "1/1"
    assert health.errors == {}


def test_forward_down_marks_tile():
    mac = MacInfo(sync=[session()], forwards=[forward("db"), forward("redis", ok=False)])
    health = build_health(mac, None, CONTAINER, EDGE, LAPTOP, {"redis": "кэш"})
    tile = health.tiles[1]
    assert tile.bad is True
    assert tile.value == "1/2"
    assert "redis" in tile.sub


def test_sync_problem_marks_tile():
    mac = MacInfo(sync=[session(), session("broken", ok=False)], forwards=[])
    health = build_health(mac, None, CONTAINER, EDGE, LAPTOP, {})
    assert health.tiles[0].bad is True
    assert "broken" in health.tiles[0].sub


def test_edge_stopped_and_missing():
    stopped = ContainerInfo("edge-proxy", False, "nginx", None, None, None)
    assert build_health(MacInfo(), None, stopped, EDGE, LAPTOP, {}).tiles[2].bad is True
    missing = build_health(MacInfo(), None, None, None, LAPTOP, {})
    assert missing.tiles[2].bad is True
    assert missing.edge == {}


def test_edge_details():
    health = build_health(MacInfo(), None, CONTAINER, EDGE, LAPTOP, {})
    assert health.edge["running"] is True
    assert health.edge["status"] == "running"
    assert health.edge["started_at"] == "2026-10-19T10:00:00Z"
    assert health.edge["http_listen"] == 80
    assert health.edge["tls_listen"] == 443
    assert any("2" in line and "TLS" in line for line in health.edge["routing"])


def test_laptop_tile():
    off = LaptopInfo(vpn=False, docker_version=None, kind_running=False)
    health = build_health(MacInfo(), None, CONTAINER, EDGE, off, {})
    assert health.tiles[3].bad is True
    assert health.tiles[3].sub.endswith("kind остановлен")
    assert health.tiles[3].sub.startswith("VPN выключен")
    assert health.tiles[3].sub != "kind остановлен"
    assert build_health(MacInfo(), None, CONTAINER, EDGE, None, {}).tiles[3].bad is True


def test_mac_errors_propagate():
    mac = MacInfo(errors={"mutagen": "no output"})
    health = build_health(mac, None, CONTAINER, EDGE, LAPTOP, {})
    assert health.errors["mutagen"] == "no output"


def test_laptop_tile_kind_stopped_not_bad():
    laptop = LaptopInfo(vpn=True, docker_version="29.9.1", kind_running=False)
    tile = build_health(MacInfo(), None, CONTAINER, EDGE, laptop, {}).tiles[3]
    assert tile.bad is False
    assert tile.sub == "Docker 29.9.1 · VPN · kind остановлен"


def test_laptop_tile_healthy_sub_from_facts():
    laptop = LaptopInfo(vpn=True, docker_version="29.9.1", kind_running=True)
    tile = build_health(MacInfo(), None, CONTAINER, EDGE, laptop, {}).tiles[3]
    assert tile.bad is False
    assert tile.sub == "Docker 29.9.1 · VPN · kind запущен"


def test_laptop_tile_vpn_off_is_bad():
    laptop = LaptopInfo(vpn=False, docker_version="29.9.1", kind_running=True)
    assert build_health(MacInfo(), None, CONTAINER, EDGE, laptop, {}).tiles[3].bad is True
