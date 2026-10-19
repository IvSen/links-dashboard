from dataclasses import dataclass
from pathlib import Path
from typing import Any

from links_dashboard.config import KIND_NODE

ROUTE_FILE = Path("/proc/net/route")
VPN_DESTINATION = "0000000A"
VPN_MASK = "00E0FFFF"


@dataclass(frozen=True)
class LaptopInfo:
    vpn: bool
    docker_version: str | None
    kind_running: bool


def has_vpn_route(route_file: Path) -> bool:
    try:
        lines = route_file.read_text().splitlines()[1:]
    except OSError:
        return False
    for line in lines:
        fields = line.split("\t")
        if len(fields) > 7 and fields[1].upper() == VPN_DESTINATION and fields[7].upper() == VPN_MASK:
            return True
    return False


def docker_version(client: Any) -> str | None:
    try:
        return client.version().get("Version")
    except Exception:
        return None


def kind_is_running(client: Any) -> bool:
    try:
        containers = client.containers.list(filters={"name": KIND_NODE})
    except Exception:
        return False
    return any(container.name == KIND_NODE for container in containers)


def read_laptop(client: Any, route_file: Path = ROUTE_FILE) -> LaptopInfo:
    return LaptopInfo(
        vpn=has_vpn_route(route_file),
        docker_version=docker_version(client),
        kind_running=kind_is_running(client),
    )
