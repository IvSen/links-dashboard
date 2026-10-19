import socket
from pathlib import Path

import pytest

from links_dashboard.cluster_source import ClusterUnavailable, IngressInfo, list_ingresses, to_ingress_info


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def write_kubeconfig(path: Path, port: int) -> Path:
    path.write_text(
        f"""apiVersion: v1
kind: Config
clusters:
- name: dead
  cluster:
    server: http://127.0.0.1:{port}
contexts:
- name: dead
  context:
    cluster: dead
    user: nobody
current-context: dead
users:
- name: nobody
  user: {{}}
"""
    )
    return path


def test_cluster_unavailable(tmp_path):
    kubeconfig = write_kubeconfig(tmp_path / "kubeconfig", closed_port())
    with pytest.raises(ClusterUnavailable) as caught:
        list_ingresses(kubeconfig)
    assert caught.value.reason


def test_cluster_unavailable_when_kubeconfig_missing(tmp_path):
    with pytest.raises(ClusterUnavailable):
        list_ingresses(tmp_path / "absent")


def test_cluster_unavailable_when_kubeconfig_broken(tmp_path):
    broken = tmp_path / "kubeconfig"
    broken.write_text("not: [valid")
    with pytest.raises(ClusterUnavailable):
        list_ingresses(broken)


def test_to_ingress_info_collects_hosts():
    from kubernetes import client

    ingress = client.V1Ingress(
        metadata=client.V1ObjectMeta(namespace="rosfines-dev", name="web"),
        spec=client.V1IngressSpec(
            rules=[
                client.V1IngressRule(host="a.test"),
                client.V1IngressRule(host=None),
                client.V1IngressRule(host="b.test"),
                client.V1IngressRule(host="a.test"),
            ]
        ),
    )
    assert to_ingress_info(ingress) == IngressInfo("rosfines-dev", "web", ["a.test", "b.test"])


def test_to_ingress_info_without_spec():
    from kubernetes import client

    ingress = client.V1Ingress(metadata=client.V1ObjectMeta(namespace="n", name="i"))
    assert to_ingress_info(ingress) == IngressInfo("n", "i", [])
