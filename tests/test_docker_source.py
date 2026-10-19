import json
from pathlib import Path

import pytest

from links_dashboard.docker_source import ContainerInfo, from_inspect, list_containers, project_of

FIXTURE = Path(__file__).parent / "fixtures" / "containers.json"


@pytest.fixture(scope="module")
def inspects() -> list[dict]:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def by_name(inspects) -> dict[str, ContainerInfo]:
    infos = [from_inspect(item) for item in inspects]
    return {info.name: info for info in infos}


def test_fixture_covers_expected_containers(by_name):
    expected = {
        "kvs-mysql", "kvs-nginx", "kvs-php", "kvs-redis", "beszel", "netdata",
        "portainer", "edge-proxy", "rosfines-dev-control-plane",
    }
    assert expected <= set(by_name)
    assert any(name.startswith("mp4kv2-panel-") for name in by_name)


def test_secret_env_dropped(by_name):
    env = by_name["kvs-mysql"].env
    assert "MYSQL_PASSWORD" not in env
    assert "MYSQL_ROOT_PASSWORD" not in env
    assert "TOKEN" not in env
    assert env["MYSQL_USER"] == "db"


def test_secret_env_dropped_in_every_container(by_name):
    for info in by_name.values():
        for name in info.env:
            assert not any(word in name.upper() for word in ("PASS", "SECRET", "TOKEN", "KEY"))


def test_compose_metadata(by_name):
    info = by_name["kvs-mysql"]
    assert info.running is True
    assert info.service == "mysql"
    assert info.project_dir == "/Users/i.senishin/project/cd_traffic/kvs"
    assert info.image == "mysql:8.0.46"
    assert info.started_at == "2026-10-18T20:39:04.192624832Z"
    assert ("0.0.0.0", 3310, 3306, "tcp") in info.ports


def test_container_without_compose_labels(by_name):
    info = by_name["portainer"]
    assert info.project_dir is None
    assert info.service is None
    assert ("127.0.0.1", 9443, 9443, "tcp") in info.ports


def test_unpublished_ports_skipped(by_name):
    assert all(port[2] != 33060 for port in by_name["kvs-mysql"].ports)


def test_ipv4_ipv6_ports_deduplicated():
    attrs = {
        "Name": "/x",
        "Config": {"Image": "img", "Env": [], "Labels": {}},
        "State": {"Running": True, "StartedAt": "2026-01-01T00:00:00Z"},
        "NetworkSettings": {
            "Ports": {
                "3306/tcp": [
                    {"HostIp": "0.0.0.0", "HostPort": "3308"},
                    {"HostIp": "::", "HostPort": "3308"},
                ]
            }
        },
    }
    assert from_inspect(attrs).ports == [("0.0.0.0", 3308, 3306, "tcp")]


def test_stopped_container_has_no_start_time():
    attrs = {
        "Name": "/x",
        "Config": {"Image": "img", "Env": None, "Labels": None},
        "State": {"Running": False, "StartedAt": "0001-01-01T00:00:00Z"},
        "NetworkSettings": {"Ports": None},
    }
    info = from_inspect(attrs)
    assert info.running is False
    assert info.started_at is None
    assert info.env == {}
    assert info.ports == []


def test_list_containers_maps_client_attrs(inspects):
    class FakeContainer:
        def __init__(self, attrs):
            self.attrs = attrs

    class FakeContainers:
        def __init__(self):
            self.kwargs = None

        def list(self, **kwargs):
            self.kwargs = kwargs
            return [FakeContainer(item) for item in inspects]

    class FakeClient:
        containers = FakeContainers()

    infos = list_containers(FakeClient())
    assert FakeClient.containers.kwargs == {"all": True}
    assert len(infos) == len(inspects)


def test_project_of():
    assert project_of("/Users/i.senishin/project/cd_traffic/kvs") == ("cd_traffic", "kvs")
    assert project_of("/Users/i.senishin/project/cd_traffic/kvs/docker") == ("cd_traffic", "kvs")
    assert project_of("/Users/i.senishin/project/cd_traffic/worktrees/mp4k_v2-set-thumbs") == (
        "cd_traffic",
        "worktrees",
    )
    assert project_of("/home/ivan/build/monitoring") == ("tools", None)
    assert project_of("/home/ivan/build/edge-proxy/sub") == ("tools", None)
    assert project_of("/tmp/x") is None
    assert project_of(None) is None
