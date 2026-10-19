import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from links_dashboard.app import create_app
from links_dashboard.cluster_source import ClusterUnavailable, IngressInfo
from links_dashboard.config import Settings
from links_dashboard.docker_source import ContainerInfo, from_inspect
from links_dashboard.laptop_source import LaptopInfo
from links_dashboard.mac_source import MacInfo, MacUnavailable
from links_dashboard.models import CheckTarget
from links_dashboard.parsers import parse_edge_conf, parse_forwards, parse_hosts, parse_sync
from links_dashboard.service import Sources
from links_dashboard.store import StateStore

FIXTURES = Path(__file__).parent / "fixtures"
HOST = {"Host": "links.test"}
KVS = {"g": "cd_traffic", "sg": "kvs"}
VIP = "web:https://vip4k.com.local"
BABYLON = "babylon.local.rf-tech.ru"
MINIO_CONSOLE = "container:mp4kv2-panel-minio:9001/tcp"
KVS_DIR = "/Users/i.senishin/project/cd_traffic/kvs"


def _mac_info() -> MacInfo:
    return MacInfo(
        hosts=parse_hosts((FIXTURES / "hosts.txt").read_text()),
        sync=parse_sync(json.loads((FIXTURES / "mutagen_sync.json").read_text())),
        forwards=parse_forwards(json.loads((FIXTURES / "mutagen_forward.json").read_text())),
        branches={KVS_DIR: "main"},
    )


def _containers() -> list[ContainerInfo]:
    return [from_inspect(item) for item in json.loads((FIXTURES / "containers.json").read_text())]


@dataclass
class World:
    mac: MacInfo = field(default_factory=_mac_info)
    containers: list[ContainerInfo] = field(default_factory=_containers)
    ingresses: list[IngressInfo] = field(
        default_factory=lambda: [IngressInfo("rosfines-dev", "babylon", [BABYLON])]
    )
    mac_error: Exception | None = None
    cluster_error: Exception | None = None
    edge_error: Exception | None = None
    container_delay: float = 0.0
    container_calls: int = 0

    def sources(self) -> Sources:
        async def mac() -> MacInfo:
            if self.mac_error is not None:
                raise self.mac_error
            return self.mac

        async def containers() -> list[ContainerInfo]:
            self.container_calls += 1
            await asyncio.sleep(self.container_delay)
            return self.containers

        async def ingresses() -> list[IngressInfo]:
            if self.cluster_error is not None:
                raise self.cluster_error
            return self.ingresses

        async def edge():
            if self.edge_error is not None:
                raise self.edge_error
            return parse_edge_conf((FIXTURES / "edge-nginx.conf").read_text())

        async def laptop() -> LaptopInfo:
            return LaptopInfo(vpn=True, docker_version="27.0", kind_running=True)

        return Sources(mac=mac, containers=containers, ingresses=ingresses, edge=edge, laptop=laptop)


async def fake_checker(targets: dict[str, CheckTarget], limit: int = 20) -> dict[str, str]:
    return {key: "na" if target.mode == "none" else "up" for key, target in targets.items()}


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(tmp_path, world):
    settings = Settings(
        state=tmp_path / "state.json",
        edge_conf=tmp_path / "edge.conf",
        kubeconfig=tmp_path / "kubeconfig",
        mac_host="mac.invalid",
        mac_user="user",
        mac_key=tmp_path / "mac_key",
        port=8099,
    )
    app = create_app(settings, sources=world.sources(), store=StateStore(settings.state), checker=fake_checker)
    with TestClient(app, headers=HOST) as test_client:
        yield test_client


def _group(client: TestClient, params: dict[str, str]) -> dict:
    response = client.get("/api/group", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _item(view: dict, key: str) -> dict:
    return next(item for item in view["items"] if item["key"] == key)


def _refresh(client: TestClient) -> dict:
    response = client.post("/api/refresh")
    assert response.status_code == 200, response.text
    return response.json()


def test_refresh_returns_tree_and_health(client):
    body = _refresh(client)
    nodes = {(node["group"], node["subgroup"]): node for node in body["tree"]}
    assert nodes[("cd_traffic", "kvs")]["count"] > 0
    assert body["tree"][0]["group"] == ""
    assert len(body["health"]["tiles"]) == 4
    assert body["failed_sources"] == {}
    assert body["checked_at"]


def test_concurrent_refresh_runs_once(client, world):
    world.container_delay = 0.3
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/api/refresh"), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert world.container_calls == 1


def test_mac_down_uses_cached_hosts(client, world):
    _refresh(client)
    world.mac_error = MacUnavailable("ssh timed out after 8s")
    body = _refresh(client)
    assert body["failed_sources"]["mac"] == "ssh timed out after 8s"
    assert body["health"]["tiles"][0]["value"] == "Мак недоступен"
    item = _item(_group(client, KVS), VIP)
    assert item["cached"] is True
    assert _item(_group(client, KVS), "container:kvs-mysql:3306/tcp")["key"]


def test_cluster_down_keeps_items(client, world):
    _refresh(client)
    world.cluster_error = ClusterUnavailable("connection refused")
    body = _refresh(client)
    assert body["failed_sources"]["cluster"] == "connection refused"
    view = _group(client, {"g": "carbox", "sg": "rosfines-dev"})
    assert _item(view, f"web:https://{BABYLON}")["status"] == "down"


def test_new_until_seen(client):
    _refresh(client)
    assert _item(_group(client, KVS), VIP)["is_new"] is True
    response = client.post("/api/seen", json={"keys": [VIP]})
    assert response.status_code == 200
    assert _item(_group(client, KVS), VIP)["is_new"] is False


def test_patch_moves_group_and_hides(client):
    _refresh(client)
    path = f"/api/items/{quote(VIP, safe='')}"
    assert client.patch(path, json={"group": "tools", "subgroup": None}).status_code == 200
    assert VIP not in {item["key"] for item in _group(client, KVS)["items"]}
    tools = _group(client, {"g": "tools"})
    assert _item(tools, VIP)["group"] == "tools"
    assert client.patch(path, json={"hidden": True}).status_code == 200
    tools = _group(client, {"g": "tools"})
    assert VIP not in {item["key"] for item in tools["items"]}
    assert VIP in {item["key"] for item in tools["hidden"]}


def test_missing_item_with_override_is_kept(client, world):
    _refresh(client)
    response = client.patch(f"/api/items/{quote(MINIO_CONSOLE, safe='')}", json={"title": "Консоль MinIO"})
    assert response.status_code == 200
    world.containers = [item for item in world.containers if item.name != "mp4kv2-panel-minio"]
    _refresh(client)
    view = _group(client, {"g": "cd_traffic", "sg": "mp4k_v2"})
    item = _item(view, MINIO_CONSOLE)
    assert item["status"] == "missing"
    assert item["title"] == "Консоль MinIO"
    assert view["items"][-1]["key"] == MINIO_CONSOLE


def test_foreign_host_rejected(client):
    assert client.get("/api/snapshot", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/refresh", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/snapshot", headers={"Host": "127.0.0.1:8099"}).status_code == 200


def test_default_description_and_project_header(client):
    _refresh(client)
    tools = _group(client, {"g": "tools"})
    assert _item(tools, "container:portainer:9443/tcp")["description"] == "Контейнеры и кластер в вебе"
    kvs = _group(client, KVS)
    assert kvs["project"]["branch"] == "main"
    assert kvs["project"]["total"] == 4
    statuses = [item["status"] for item in kvs["items"]]
    assert statuses == sorted(statuses, key=["up", "down", "na", "missing"].index)


def test_patch_rejects_unknown_key_and_field(client):
    _refresh(client)
    assert client.patch("/api/items/web:http://nope.test", json={"title": "x"}).status_code == 404
    assert client.patch(f"/api/items/{VIP}", json={"color": "red"}).status_code == 422
    assert client.patch(f"/api/items/{VIP}", json={"kind": "ftp"}).status_code == 422


def test_notes_groups_and_purpose_persist(client, tmp_path):
    _refresh(client)
    assert client.put("/api/notes", json={"scope": "cd_traffic/kvs", "text": "admin / admin\n"}).status_code == 200
    assert client.post("/api/groups", json={"group": "home", "subgroup": "links"}).status_code == 200
    assert client.put("/api/forward-purpose", json={"name": "portainer", "text": "Portainer"}).status_code == 200
    assert _group(client, KVS)["note"] == "admin / admin\n"
    snapshot = client.get("/api/snapshot").json()
    assert ("home", "links") in {(node["group"], node["subgroup"]) for node in snapshot["tree"]}
    portainer = next(row for row in snapshot["health"]["forwards"] if row["name"] == "portainer")
    assert portainer["purpose"] == "Portainer"
    saved = StateStore(tmp_path / "state.json").load()
    assert saved.notes["cd_traffic/kvs"] == "admin / admin\n"
    assert saved.forward_purpose["portainer"] == "Portainer"
    assert VIP in saved.known


def test_broken_edge_config_keeps_last_routes(client, world):
    _refresh(client)
    world.edge_error = ValueError("no stream block")
    body = _refresh(client)
    assert body["failed_sources"]["edge"] == "ValueError: no stream block"
    assert len(body["health"]["tiles"]) == 4
    assert _item(_group(client, {"g": "tools"}), "web:http://beszel.test")["status"] == "up"


def _pin(client: TestClient, key: str, pinned: bool = True):
    return client.put("/api/pins", json={"key": key, "pinned": pinned})


def _pinned(client: TestClient) -> list[dict]:
    response = client.get("/api/pinned")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_pin_lists_item_with_status_and_place(client, tmp_path):
    _refresh(client)
    assert _pinned(client) == []
    assert _pin(client, VIP).status_code == 200
    items = _pinned(client)
    assert [item["key"] for item in items] == [VIP]
    assert items[0]["status"] == "up"
    assert items[0]["pinned"] is True
    assert (items[0]["group"], items[0]["subgroup"]) == ("cd_traffic", "kvs")
    assert _item(_group(client, KVS), VIP)["pinned"] is True
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["pinned"] == [VIP]
    assert _pin(client, VIP, False).status_code == 200
    assert _pinned(client) == []
    assert _item(_group(client, KVS), VIP)["pinned"] is False


def test_pinned_order_answering_first_then_pin_order(client, world):
    _refresh(client)
    assert _pin(client, MINIO_CONSOLE).status_code == 200
    assert _pin(client, VIP).status_code == 200
    assert [item["key"] for item in _pinned(client)] == [MINIO_CONSOLE, VIP]
    world.containers = [item for item in world.containers if item.name != "mp4kv2-panel-minio"]
    _refresh(client)
    items = _pinned(client)
    assert [(item["key"], item["status"]) for item in items] == [(VIP, "up"), (MINIO_CONSOLE, "missing")]


def test_hiding_unpins(client):
    _refresh(client)
    assert _pin(client, VIP).status_code == 200
    assert client.patch(f"/api/items/{quote(VIP, safe='')}", json={"hidden": True}).status_code == 200
    assert _pinned(client) == []


def test_pin_rejects_unknown_key(client):
    _refresh(client)
    response = _pin(client, "web:https://nope.local")
    assert response.status_code == 404
    assert client.put("/api/pins", json={"key": VIP}).status_code == 422


def test_hidden_item_cannot_be_pinned(client):
    _refresh(client)
    assert client.patch(f"/api/items/{quote(VIP, safe='')}", json={"hidden": True}).status_code == 200
    assert _pin(client, VIP).status_code == 200
    assert _pinned(client) == []
    hidden = _group(client, KVS)["hidden"]
    assert next(item for item in hidden if item["key"] == VIP)["pinned"] is False
