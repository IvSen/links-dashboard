import re
from dataclasses import dataclass, field

from links_dashboard.cluster_source import IngressInfo
from links_dashboard.config import (
    CONN_PORTS,
    EDGE_CONTAINER,
    KIND_NODE,
    KNOWN_HOSTS,
    NAMESPACE_GROUPS,
    TOOL_CONTAINERS,
)
from links_dashboard.docker_source import PROJECT_ROOT, ContainerInfo, Port, project_of
from links_dashboard.models import CheckTarget, Endpoint
from links_dashboard.parsers import EdgeRoutes, Forward

LOOPBACK = "127.0.0.1"
MAC_WEB_HOST = "localhost"
LOOPBACK_BINDINGS = frozenset({LOOPBACK, "0.0.0.0", "", "::"})
SKIPPED_CONTAINERS = frozenset({KIND_NODE, EDGE_CONTAINER})
IMAGE_PROTOS = (
    ("mysql", "MySQL"),
    ("postgres", "PostgreSQL"),
    ("redis", "Redis"),
    ("rabbitmq", "RabbitMQ"),
    ("mongo", "MongoDB"),
    ("clickhouse", "ClickHouse"),
)
USER_ENV = (
    "MYSQL_USER",
    "MARIADB_USER",
    "POSTGRES_USER",
    "MONGO_INITDB_ROOT_USERNAME",
    "RABBITMQ_DEFAULT_USER",
    "CLICKHOUSE_USER",
    "MINIO_ROOT_USER",
)
DB_ENV = (
    "MYSQL_DATABASE",
    "MARIADB_DATABASE",
    "POSTGRES_DB",
    "MONGO_INITDB_DATABASE",
    "CLICKHOUSE_DB",
)

Group = tuple[str | None, str | None]
NO_GROUP: Group = (None, None)


@dataclass(frozen=True)
class ProjectInfo:
    group: str
    subgroup: str
    folder: str
    branch: str | None
    running: int
    total: int
    stopped: list[str] = field(default_factory=list)


def _container_group(container: ContainerInfo) -> Group:
    project = project_of(container.project_dir)
    if project is not None:
        return project
    return TOOL_CONTAINERS.get(container.name, NO_GROUP)


def _port_owners(containers: list[ContainerInfo]) -> dict[int, ContainerInfo]:
    owners: dict[int, ContainerInfo] = {}
    for container in containers:
        for host_ip, host_port, _, _ in container.ports:
            if host_ip in LOOPBACK_BINDINGS:
                owners.setdefault(host_port, container)
    return owners


def _has_explicit(routes: list[tuple[str, bool, int]], name: str) -> bool:
    return any(not is_regex and pattern.lower() == name for pattern, is_regex, _ in routes)


def _ingress_groups(ingresses: list[IngressInfo]) -> dict[str, Group]:
    groups: dict[str, Group] = {}
    for ingress in ingresses:
        for host in ingress.hosts:
            groups.setdefault(host.lower(), NAMESPACE_GROUPS.get(ingress.namespace, NO_GROUP))
    return groups


def _host_group(
    name: str,
    port: int,
    owners: dict[int, ContainerInfo],
    ingress_groups: dict[str, Group],
) -> Group:
    if name in KNOWN_HOSTS:
        return KNOWN_HOSTS[name]
    owner = owners.get(port)
    group = _container_group(owner) if owner is not None else NO_GROUP
    if group == NO_GROUP:
        return ingress_groups.get(name, NO_GROUP)
    return group


def _host_endpoint(
    name: str,
    edge: EdgeRoutes,
    owners: dict[int, ContainerInfo],
    ingress_groups: dict[str, Group],
) -> Endpoint:
    is_http = _has_explicit(edge.http, name) and not _has_explicit(edge.tls, name)
    if is_http:
        scheme, mode, listen, port = "http", "http", edge.http_listen, edge.route_http(name)
    else:
        scheme, mode, listen, port = "https", "https_sni", edge.tls_listen, edge.route_tls(name)
    group, subgroup = _host_group(name, port, owners, ingress_groups)
    url = f"{scheme}://{name}"
    return Endpoint(
        key=f"web:{url}",
        kind="web",
        label=name,
        url=url,
        source="hosts",
        group=group,
        subgroup=subgroup,
        reachable_from_mac=True,
        check=CheckTarget(mode, LOOPBACK, listen, name),
    )


def _ingress_endpoint(host: str, namespace: str, edge: EdgeRoutes) -> Endpoint:
    group, subgroup = NAMESPACE_GROUPS.get(namespace, NO_GROUP)
    url = f"https://{host}"
    return Endpoint(
        key=f"web:{url}",
        kind="web",
        label=host,
        url=url,
        source="cluster",
        group=group,
        subgroup=subgroup,
        reachable_from_mac=True,
        check=CheckTarget("https_sni", LOOPBACK, edge.tls_listen, host),
    )


def _edge_backends(edge: EdgeRoutes) -> frozenset[int]:
    targets = [port for _, _, port in edge.http + edge.tls]
    return frozenset(targets + [edge.http_default, edge.tls_default])


def _conn_proto(container_port: int, image: str) -> str | None:
    if container_port in CONN_PORTS:
        return CONN_PORTS[container_port]
    lowered = image.lower()
    return next((proto for marker, proto in IMAGE_PROTOS if marker in lowered), None)


def _first_env(env: dict[str, str], names: tuple[str, ...]) -> str | None:
    return next((env[name] for name in names if env.get(name)), None)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _conn_details(container: ContainerInfo, proto: str, src_port: int) -> dict[str, str]:
    optional = {
        "user": _first_env(container.env, USER_ENV),
        "db": _first_env(container.env, DB_ENV),
    }
    base = {"proto": proto, "address": f"{LOOPBACK}:{src_port}", "container": container.name}
    return {**base, **{key: value for key, value in optional.items() if value}}


def _conn_label(details: dict[str, str]) -> str:
    parts = [f"{details['proto']} {details['address']}"]
    parts += [f"user {details['user']}"] if "user" in details else []
    parts += [f"db {details['db']}"] if "db" in details else []
    return " · ".join(parts)


def _forwarded_endpoint(
    container: ContainerInfo, port: Port, src_port: int, proto: str | None
) -> Endpoint:
    _, host_port, _, _ = port
    group, subgroup = _container_group(container)
    common = {"source": "container", "group": group, "subgroup": subgroup, "reachable_from_mac": True}
    if proto is not None:
        details = _conn_details(container, proto, src_port)
        return Endpoint(
            key=f"conn:{_slug(proto)}:{LOOPBACK}:{src_port}",
            kind="conn",
            label=_conn_label(details),
            url=None,
            check=CheckTarget("tcp", LOOPBACK, host_port, None),
            details=details,
            **common,
        )
    url = f"http://{MAC_WEB_HOST}:{src_port}"
    return Endpoint(
        key=f"web:{url}",
        kind="web",
        label=f"{MAC_WEB_HOST}:{src_port}",
        url=url,
        check=CheckTarget("http", LOOPBACK, host_port, None),
        details={"container": container.name},
        **common,
    )


def _unreachable_endpoint(container: ContainerInfo, port: Port, proto: str | None) -> Endpoint:
    _, host_port, container_port, _ = port
    group, subgroup = _container_group(container)
    return Endpoint(
        key=f"unreachable:{container.name}:{container_port}",
        kind="conn" if proto is not None else "web",
        label=f"{container.name} :{container_port}",
        url=None,
        source="container",
        group=group,
        subgroup=subgroup,
        reachable_from_mac=False,
        check=CheckTarget("none", LOOPBACK, host_port, None),
        details={"container": container.name},
    )


def _container_endpoints(
    container: ContainerInfo, backends: frozenset[int], mac_ports: dict[int, int]
) -> list[Endpoint]:
    result = []
    for port in container.ports:
        _, host_port, container_port, _ = port
        if host_port in backends:
            continue
        proto = _conn_proto(container_port, container.image)
        src_port = mac_ports.get(host_port)
        if src_port is None:
            result.append(_unreachable_endpoint(container, port, proto))
        else:
            result.append(_forwarded_endpoint(container, port, src_port, proto))
    return result


def _mac_ports(forwards: list[Forward]) -> dict[int, int]:
    ports: dict[int, int] = {}
    for forward in forwards:
        if not forward.reverse and forward.dest_port is not None and forward.src_port is not None:
            ports.setdefault(forward.dest_port, forward.src_port)
    return ports


def _dedup(endpoints: list[Endpoint]) -> list[Endpoint]:
    unique: dict[str, Endpoint] = {}
    for endpoint in endpoints:
        unique.setdefault(endpoint.key, endpoint)
    return list(unique.values())


def build_endpoints(
    hosts: list[str],
    containers: list[ContainerInfo],
    ingresses: list[IngressInfo],
    edge: EdgeRoutes,
    forwards: list[Forward],
) -> list[Endpoint]:
    """Turn raw source data into endpoints; on duplicate keys the earlier rule wins."""
    owners = _port_owners(containers)
    ingress_groups = _ingress_groups(ingresses)
    from_hosts = [_host_endpoint(name.lower(), edge, owners, ingress_groups) for name in hosts]
    from_cluster = [
        _ingress_endpoint(host.lower(), ingress.namespace, edge)
        for ingress in ingresses
        for host in ingress.hosts
    ]
    backends = _edge_backends(edge)
    mac_ports = _mac_ports(forwards)
    from_containers = [
        endpoint
        for container in containers
        if container.name not in SKIPPED_CONTAINERS
        for endpoint in _container_endpoints(container, backends, mac_ports)
    ]
    return _dedup(from_hosts + from_cluster + from_containers)


def build_projects(containers: list[ContainerInfo], branches: dict[str, str]) -> list[ProjectInfo]:
    """Summarise compose projects under the Mac project root, sorted by group and subgroup."""
    members: dict[tuple[str, str], list[ContainerInfo]] = {}
    for container in containers:
        project = project_of(container.project_dir)
        if project is not None and project[1] is not None:
            members.setdefault((project[0], project[1]), []).append(container)
    return [
        _project_info(group, subgroup, items, branches)
        for (group, subgroup), items in sorted(members.items())
    ]


def _project_info(
    group: str, subgroup: str, items: list[ContainerInfo], branches: dict[str, str]
) -> ProjectInfo:
    folder = f"{PROJECT_ROOT}{group}/{subgroup}"
    stopped = sorted(item.name for item in items if not item.running)
    return ProjectInfo(
        group=group,
        subgroup=subgroup,
        folder=folder,
        branch=branches.get(folder),
        running=len(items) - len(stopped),
        total=len(items),
        stopped=stopped,
    )
