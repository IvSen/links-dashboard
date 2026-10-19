from dataclasses import dataclass, field
from typing import Any

SECRET_MARKERS = ("PASS", "SECRET", "TOKEN", "KEY")
PROJECT_ROOT = "/Users/i.senishin/project/"
BUILD_ROOT = "/home/ivan/build/"
ZERO_TIME_PREFIX = "0001-01-01"
LABEL_DIR = "com.docker.compose.project.working_dir"
LABEL_SERVICE = "com.docker.compose.service"

Port = tuple[str, int, int, str]


@dataclass(frozen=True)
class ContainerInfo:
    name: str
    running: bool
    image: str
    started_at: str | None
    project_dir: str | None
    service: str | None
    env: dict[str, str] = field(default_factory=dict)
    ports: list[Port] = field(default_factory=list)


def is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in SECRET_MARKERS)


def parse_env(items: list[str] | None) -> dict[str, str]:
    pairs = (item.partition("=") for item in items or [])
    return {key: value for key, _, value in pairs if not is_secret_name(key)}


def parse_ports(published: dict[str, Any] | None) -> list[Port]:
    seen: dict[tuple[int, int, str], Port] = {}
    for spec, bindings in (published or {}).items():
        container_port, _, proto = spec.partition("/")
        for binding in bindings or []:
            host_port = binding.get("HostPort")
            if not host_port:
                continue
            key = (int(host_port), int(container_port), proto)
            seen.setdefault(key, (binding.get("HostIp", ""), key[0], key[1], proto))
    return list(seen.values())


def published_ports(attrs: dict[str, Any], running: bool) -> list[Port]:
    """Live port map of a running container; the configured bindings of a stopped one."""
    if running:
        return parse_ports((attrs.get("NetworkSettings") or {}).get("Ports"))
    return parse_ports((attrs.get("HostConfig") or {}).get("PortBindings"))


def parse_started_at(state: dict[str, Any]) -> str | None:
    started = state.get("StartedAt")
    if not started or started.startswith(ZERO_TIME_PREFIX):
        return None
    return started


def from_inspect(attrs: dict[str, Any]) -> ContainerInfo:
    config = attrs.get("Config") or {}
    labels = config.get("Labels") or {}
    state = attrs.get("State") or {}
    running = bool(state.get("Running"))
    return ContainerInfo(
        name=attrs["Name"].lstrip("/"),
        running=running,
        image=config.get("Image", ""),
        started_at=parse_started_at(state),
        project_dir=labels.get(LABEL_DIR),
        service=labels.get(LABEL_SERVICE),
        env=parse_env(config.get("Env")),
        ports=published_ports(attrs, running),
    )


def list_containers(client: Any) -> list[ContainerInfo]:
    return [from_inspect(container.attrs) for container in client.containers.list(all=True)]


def project_of(path: str | None) -> tuple[str, str | None] | None:
    if not path:
        return None
    if path.startswith(PROJECT_ROOT):
        parts = path[len(PROJECT_ROOT):].split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
        return None
    if path.startswith(BUILD_ROOT) and path[len(BUILD_ROOT):].split("/")[0]:
        return "tools", None
    return None
