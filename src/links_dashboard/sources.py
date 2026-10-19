import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import docker
from docker.errors import DockerException

from links_dashboard.cluster_source import ClusterUnavailable, IngressInfo, list_ingresses
from links_dashboard.config import Settings
from links_dashboard.docker_source import ContainerInfo, list_containers
from links_dashboard.laptop_source import ROUTE_FILE, LaptopInfo, has_vpn_route, read_laptop
from links_dashboard.mac_files import with_file_fallback
from links_dashboard.mac_source import MacInfo, MacUnavailable, fetch_mac_info
from links_dashboard.parsers import EdgeRoutes, parse_edge_conf

logger = logging.getLogger(__name__)

REASON_LIMIT = 300
T = TypeVar("T")


@dataclass(frozen=True)
class Sources:
    mac: Callable[[], Awaitable[MacInfo]]
    containers: Callable[[], Awaitable[list[ContainerInfo]]]
    ingresses: Callable[[], Awaitable[list[IngressInfo]]]
    edge: Callable[[], Awaitable[EdgeRoutes]]
    laptop: Callable[[], Awaitable[LaptopInfo]]


@dataclass(frozen=True)
class Fetched:
    mac: MacInfo | None
    containers: list[ContainerInfo] | None
    ingresses: list[IngressInfo] | None
    edge: EdgeRoutes | None
    laptop: LaptopInfo | None
    failed: dict[str, str] = field(default_factory=dict)


async def _attempt(name: str, call: Callable[[], Awaitable[T]]) -> tuple[T | None, str | None]:
    try:
        return await call(), None
    except (MacUnavailable, ClusterUnavailable) as error:
        logger.warning("source %s unavailable: %s", name, error.reason)
        return None, error.reason
    except Exception as error:
        logger.exception("source %s failed", name)
        return None, f"{type(error).__name__}: {error}"[:REASON_LIMIT]


async def fetch_all(sources: Sources) -> Fetched:
    """Call every source concurrently; a failing source yields None and a reason, the rest goes on."""
    calls = {
        "mac": sources.mac,
        "docker": sources.containers,
        "cluster": sources.ingresses,
        "edge": sources.edge,
        "laptop": sources.laptop,
    }
    results = await asyncio.gather(*(_attempt(name, call) for name, call in calls.items()))
    values = {name: value for name, (value, _) in zip(calls, results)}
    failed = {name: reason for name, (_, reason) in zip(calls, results) if reason is not None}
    return Fetched(
        mac=values["mac"],
        containers=values["docker"],
        ingresses=values["cluster"],
        edge=values["edge"],
        laptop=values["laptop"],
        failed=failed,
    )


def _with_docker(action: Callable[[Any], T]) -> T:
    client = docker.from_env()
    try:
        return action(client)
    finally:
        client.close()


def _laptop_info() -> LaptopInfo:
    try:
        return _with_docker(read_laptop)
    except DockerException as error:
        logger.warning("docker unavailable for the laptop tile: %s", error)
        return LaptopInfo(vpn=has_vpn_route(ROUTE_FILE), docker_version=None, kind_running=False)


def _read_edge(path: Path) -> EdgeRoutes:
    return parse_edge_conf(path.read_text(encoding="utf-8"))


def real_sources(settings: Settings) -> Sources:
    """Sources talking to the real Mac, Docker, cluster and edge config; nothing runs until called."""

    async def over_ssh() -> MacInfo:
        return await fetch_mac_info(settings.mac_host, settings.mac_user, settings.mac_key)

    async def mac() -> MacInfo:
        return await with_file_fallback(over_ssh, settings.mac_files)

    async def containers() -> list[ContainerInfo]:
        return await asyncio.to_thread(_with_docker, list_containers)

    async def ingresses() -> list[IngressInfo]:
        return await asyncio.to_thread(list_ingresses, settings.kubeconfig)

    async def edge() -> EdgeRoutes:
        return await asyncio.to_thread(_read_edge, settings.edge_conf)

    async def laptop() -> LaptopInfo:
        return await asyncio.to_thread(_laptop_info)

    return Sources(mac=mac, containers=containers, ingresses=ingresses, edge=edge, laptop=laptop)
