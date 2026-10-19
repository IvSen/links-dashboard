import os
from dataclasses import dataclass
from pathlib import Path

NAMESPACE_GROUPS = {"rosfines-dev": ("carbox", "rosfines-dev")}
TOOL_CONTAINERS = {"portainer": ("tools", None)}
KNOWN_HOSTS = {"netdata.test": ("tools", None), "links.test": ("tools", None)}
KIND_NODE = "rosfines-dev-control-plane"
EDGE_CONTAINER = "edge-proxy"
EDGE_HTTP_LISTEN = 10080
EDGE_TLS_LISTEN = 10443
CONN_PORTS = {
    3306: "MySQL",
    5432: "PostgreSQL",
    6379: "Redis",
    5672: "RabbitMQ",
    27017: "MongoDB",
    9000: "MinIO API",
    8123: "ClickHouse",
}
TLS_PORTS = frozenset({443, 8443, 9443})
DEFAULT_DESCRIPTIONS = {
    "container:portainer:9443/tcp": "Контейнеры и кластер в вебе",
    "web:http://beszel.test": "Нагрузка ноутбука и история",
    "web:http://netdata.test": "Подробные метрики по секундам",
    "container:mp4kv2-panel-minio:9001/tcp": "Веб-консоль MinIO (mp4k_v2)",
}


@dataclass(frozen=True)
class Settings:
    state: Path
    edge_conf: Path
    kubeconfig: Path
    mac_host: str
    mac_user: str
    mac_key: Path
    port: int

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            state=Path(env.get("LD_STATE", "/data/state.json")),
            edge_conf=Path(env.get("LD_EDGE_CONF", "/config/edge-nginx.conf")),
            kubeconfig=Path(env.get("LD_KUBECONFIG", "/data/kubeconfig")),
            mac_host=env.get("LD_MAC_HOST", "10.0.100.243"),
            mac_user=env.get("LD_MAC_USER", "i.senishin"),
            mac_key=Path(env.get("LD_MAC_KEY", "/data/mac_key")),
            port=int(env.get("LD_PORT", "8099")),
        )
