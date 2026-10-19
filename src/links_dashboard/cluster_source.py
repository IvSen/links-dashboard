from dataclasses import dataclass
from pathlib import Path

import yaml
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from urllib3.exceptions import HTTPError

CONNECT_TIMEOUT = 2
READ_TIMEOUT = 3
REQUEST_TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)
CLUSTER_ERRORS = (
    client.ApiException,
    ConfigException,
    HTTPError,
    yaml.YAMLError,
    OSError,
    ValueError,
    KeyError,
    TypeError,
)


class ClusterUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class IngressInfo:
    namespace: str
    name: str
    hosts: list[str]


def to_ingress_info(ingress: client.V1Ingress) -> IngressInfo:
    rules = ingress.spec.rules if ingress.spec and ingress.spec.rules else []
    hosts = list(dict.fromkeys(rule.host for rule in rules if rule.host))
    return IngressInfo(ingress.metadata.namespace, ingress.metadata.name, hosts)


def list_ingresses(kubeconfig: Path) -> list[IngressInfo]:
    try:
        api_client = config.new_client_from_config(
            config_file=str(kubeconfig),
            client_configuration=client.Configuration(retries=False),
        )
        api = client.NetworkingV1Api(api_client)
        items = api.list_ingress_for_all_namespaces(_request_timeout=REQUEST_TIMEOUT).items
        return [to_ingress_info(item) for item in items]
    except CLUSTER_ERRORS as error:
        raise ClusterUnavailable(f"{type(error).__name__}: {error}"[:300]) from error
