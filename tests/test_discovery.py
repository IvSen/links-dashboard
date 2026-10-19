import copy
import json
from pathlib import Path

import pytest

from links_dashboard.cluster_source import IngressInfo
from links_dashboard.discovery import ProjectInfo, build_endpoints, build_projects
from links_dashboard.docker_source import ContainerInfo, from_inspect
from links_dashboard.models import Endpoint
from links_dashboard.parsers import Forward, parse_edge_conf, parse_forwards, parse_hosts

FIXTURES = Path(__file__).parent / "fixtures"
KVS_DIR = "/Users/i.senishin/project/cd_traffic/kvs"
BABYLON = "babylon.local.rf-tech.ru"


@pytest.fixture(scope="module")
def inspects() -> list[dict]:
    return json.loads((FIXTURES / "containers.json").read_text())


@pytest.fixture(scope="module")
def containers(inspects) -> list[ContainerInfo]:
    return [from_inspect(item) for item in inspects]


@pytest.fixture(scope="module")
def hosts() -> list[str]:
    return parse_hosts((FIXTURES / "hosts.txt").read_text())


@pytest.fixture(scope="module")
def edge():
    return parse_edge_conf((FIXTURES / "edge-nginx.conf").read_text())


@pytest.fixture(scope="module")
def forwards() -> list[Forward]:
    return parse_forwards(json.loads((FIXTURES / "mutagen_forward.json").read_text()))


@pytest.fixture(scope="module")
def ingresses() -> list[IngressInfo]:
    return [IngressInfo("rosfines-dev", "babylon", [BABYLON])]


@pytest.fixture(scope="module")
def endpoints(hosts, containers, ingresses, edge, forwards) -> dict[str, Endpoint]:
    built = build_endpoints(hosts, containers, ingresses, edge, forwards)
    return {item.key: item for item in built}


def test_vip4k_goes_to_kvs(endpoints):
    item = endpoints["web:https://vip4k.com.local"]
    assert (item.group, item.subgroup) == ("cd_traffic", "kvs")
    assert item.check.mode == "https_sni"
    assert item.check.port == 10443
    assert item.check.server_name == "vip4k.com.local"
    assert item.source == "hosts"
    assert item.reachable_from_mac is True


def test_beszel_is_http_tools(endpoints):
    item = endpoints["web:http://beszel.test"]
    assert item.group == "tools"
    assert item.check.mode == "http"
    assert item.check.port == 10080
    assert item.check.server_name == "beszel.test"


def test_netdata_uses_known_hosts(endpoints):
    item = endpoints["web:http://netdata.test"]
    assert (item.group, item.subgroup) == ("tools", None)


def test_ingress_goes_to_rosfines(endpoints):
    item = endpoints[f"web:https://{BABYLON}"]
    assert (item.group, item.subgroup) == ("carbox", "rosfines-dev")
    assert item.source == "cluster"
    assert item.check.mode == "https_sni"
    assert item.check.port == 10443
    assert item.check.server_name == BABYLON


def test_kvs_mysql_is_connection(endpoints):
    item = endpoints["conn:mysql:127.0.0.1:3310"]
    assert item.kind == "conn"
    assert item.url is None
    assert "user db" in item.label
    assert item.label.startswith("MySQL 127.0.0.1:3310")
    assert (item.group, item.subgroup) == ("cd_traffic", "kvs")
    assert (item.check.mode, item.check.host, item.check.port) == ("tcp", "127.0.0.1", 3310)
    assert "PASSWORD" not in item.label.upper()
    assert all("PASSWORD" not in f"{k}={v}".upper() for k, v in item.details.items())


def test_minio_console_is_web_and_api_is_conn(endpoints):
    console = endpoints["web:http://localhost:19001"]
    assert console.kind == "web"
    assert (console.group, console.subgroup) == ("cd_traffic", "mp4k_v2")
    assert (console.check.mode, console.check.port) == ("http", 19001)
    api = endpoints["conn:minio-api:127.0.0.1:19000"]
    assert api.kind == "conn"


def test_portainer_is_https(endpoints):
    item = endpoints["web:https://localhost:9443"]
    assert (item.group, item.subgroup) == ("tools", None)
    assert item.url == "https://localhost:9443"
    assert item.check.mode == "https_sni"
    assert item.check.port == 9443
    assert item.check.server_name is None
    assert "web:http://localhost:9443" not in endpoints


def test_unforwarded_port_is_grey(hosts, containers, ingresses, edge, forwards):
    without_console = [item for item in forwards if item.name != "mp4k-minio-console"]
    built = build_endpoints(hosts, containers, ingresses, edge, without_console)
    by_key = {item.key: item for item in built}
    item = by_key["unreachable:mp4kv2-panel-minio:9001"]
    assert item.reachable_from_mac is False
    assert item.check.mode == "none"
    assert item.label == "mp4kv2-panel-minio :9001"
    assert item.url is None
    assert "web:http://localhost:19001" not in by_key


def test_reverse_forward_does_not_make_reachable(hosts, containers, ingresses, edge, forwards):
    reversed_mysql = [
        Forward(**{**vars(item), "reverse": True}) if item.name == "kvs-mysql" else item
        for item in forwards
    ]
    built = build_endpoints(hosts, containers, ingresses, edge, reversed_mysql)
    keys = {item.key for item in built}
    assert "conn:mysql:127.0.0.1:3310" not in keys
    assert "unreachable:kvs-mysql:3306" in keys


def test_edge_backends_not_listed(endpoints):
    assert not [key for key in endpoints if ":8080" in key or ":8095" in key]
    assert not [key for key in endpoints if ":8443" in key]


def test_kind_and_edge_containers_skipped(endpoints):
    assert not [key for key in endpoints if "64565" in key]
    assert all(item.source != "container" or "rosfines-dev-control-plane" not in item.key
               for item in endpoints.values())


def test_keys_unique_and_first_rule_wins(hosts, containers, edge, forwards):
    ingress = [IngressInfo("rosfines-dev", "dup", ["beszel.test"])]
    built = build_endpoints(hosts + ["beszel.test"], containers, ingress, edge, forwards)
    keys = [item.key for item in built]
    assert len(keys) == len(set(keys))
    beszel = next(item for item in built if item.key == "web:http://beszel.test")
    assert beszel.source == "hosts"


def test_projects_running_counts(inspects):
    flipped = copy.deepcopy(inspects)
    for item in flipped:
        if item["Name"].lstrip("/") == "kvs-redis":
            item["State"]["Running"] = False
    containers = [from_inspect(item) for item in flipped]
    projects = build_projects(containers, {KVS_DIR: "feature/x"})
    kvs = next(p for p in projects if (p.group, p.subgroup) == ("cd_traffic", "kvs"))
    assert isinstance(kvs, ProjectInfo)
    assert kvs.total == 4
    assert kvs.running == 3
    assert kvs.stopped == ["kvs-redis"]
    assert kvs.branch == "feature/x"
    assert kvs.folder == KVS_DIR


def test_projects_skip_tools_and_unknown_branch(containers):
    projects = build_projects(containers, {})
    pairs = [(p.group, p.subgroup) for p in projects]
    assert pairs == sorted(pairs)
    assert ("cd_traffic", "mp4k_v2") in pairs
    assert all(p.group != "tools" for p in projects)
    assert all(p.branch is None for p in projects)
