import json
import os
import tempfile
import zlib
from dataclasses import replace
from pathlib import Path

from links_dashboard.cluster_source import ClusterUnavailable, IngressInfo
from links_dashboard.config import Settings
from links_dashboard.docker_source import ContainerInfo, from_inspect
from links_dashboard.laptop_source import LaptopInfo
from links_dashboard.mac_source import MacInfo, MacUnavailable
from links_dashboard.models import CheckTarget
from links_dashboard.parsers import EdgeRoutes, parse_edge_conf, parse_forwards, parse_hosts, parse_sync
from links_dashboard.sources import Sources

DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
STOPPED_CONTAINER = "kvs-redis"
BROKEN_FORWARD = "kind-api"
KVS_DIR = "/Users/i.senishin/project/cd_traffic/kvs"
FAKE_BRANCH = "ivsen/sidebar-upgrade-css"
DOWN_EVERY = 6


def _read(fixtures: Path, name: str) -> str:
    return (fixtures / name).read_text(encoding="utf-8")


def _mac_info(fixtures: Path) -> MacInfo:
    forwards = [
        replace(forward, ok=False, status_text="не подключён") if forward.name == BROKEN_FORWARD else forward
        for forward in parse_forwards(json.loads(_read(fixtures, "mutagen_forward.json")))
    ]
    return MacInfo(
        hosts=parse_hosts(_read(fixtures, "hosts.txt")),
        sync=parse_sync(json.loads(_read(fixtures, "mutagen_sync.json"))),
        forwards=forwards,
        branches={KVS_DIR: FAKE_BRANCH},
    )


def _containers(fixtures: Path) -> list[ContainerInfo]:
    parsed = [from_inspect(item) for item in json.loads(_read(fixtures, "containers.json"))]
    return [replace(c, running=False) if c.name == STOPPED_CONTAINER else c for c in parsed]


def fake_sources(fixtures: Path = DEFAULT_FIXTURES, failing: frozenset[str] = frozenset()) -> Sources:
    """Fixture-backed sources for a local look at the page; names in `failing` raise like a dead source."""

    async def mac() -> MacInfo:
        if "mac" in failing:
            raise MacUnavailable("timeout")
        return _mac_info(fixtures)

    async def containers() -> list[ContainerInfo]:
        return _containers(fixtures)

    async def ingresses() -> list[IngressInfo]:
        if "cluster" in failing:
            raise ClusterUnavailable("connection refused")
        return [IngressInfo("rosfines-dev", "babylon", ["babylon.local.rf-tech.ru"])]

    async def edge() -> EdgeRoutes:
        return parse_edge_conf(_read(fixtures, "edge-nginx.conf"))

    async def laptop() -> LaptopInfo:
        return LaptopInfo(vpn=True, docker_version="27.0", kind_running=True)

    return Sources(mac=mac, containers=containers, ingresses=ingresses, edge=edge, laptop=laptop)


async def fake_checker(targets: dict[str, CheckTarget], limit: int = 20) -> dict[str, str]:
    """Deterministic statuses without any network: unreachable targets are "na", a few others are down."""
    return {
        key: "na" if target.mode == "none" else ("down" if zlib.crc32(key.encode()) % DOWN_EVERY == 0 else "up")
        for key, target in targets.items()
    }


def fake_settings() -> Settings:
    """Real settings, but the state file goes to a temp dir unless LD_STATE points elsewhere."""
    settings = Settings.from_env()
    if "LD_STATE" in os.environ:
        return settings
    return replace(settings, state=Path(tempfile.gettempdir()) / "links-dashboard-fake" / "state.json")


def failing_from_env() -> frozenset[str]:
    raw = os.environ.get("LD_FAKE_FAIL", "")
    return frozenset(name.strip() for name in raw.split(",") if name.strip())
