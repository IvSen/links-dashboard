from pathlib import Path

from links_dashboard.config import DEFAULT_DESCRIPTIONS, KNOWN_HOSTS, TLS_PORTS, Settings


def test_defaults(monkeypatch):
    for name in ("LD_STATE", "LD_EDGE_CONF", "LD_KUBECONFIG", "LD_MAC_HOST", "LD_MAC_USER", "LD_MAC_KEY", "LD_PORT", "LD_MAC_FILES"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.state == Path("/data/state.json")
    assert settings.edge_conf == Path("/config/edge-nginx.conf")
    assert settings.kubeconfig == Path("/data/kubeconfig")
    assert settings.mac_host == "10.0.100.243"
    assert settings.mac_user == "i.senishin"
    assert settings.mac_key == Path("/data/mac_key")
    assert settings.port == 8099
    assert settings.mac_files == Path("/data/mac")


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("LD_PORT", "9000")
    monkeypatch.setenv("LD_STATE", "/tmp/s.json")
    monkeypatch.setenv("LD_MAC_FILES", "/tmp/mac")
    settings = Settings.from_env()
    assert settings.mac_files == Path("/tmp/mac")
    assert settings.port == 9000
    assert settings.state == Path("/tmp/s.json")


def test_known_hosts():
    assert KNOWN_HOSTS == {"netdata.test": ("tools", None), "links.test": ("tools", None)}


def test_default_description_keys():
    assert DEFAULT_DESCRIPTIONS["container:portainer:9443/tcp"] == "Контейнеры и кластер в вебе"
    assert DEFAULT_DESCRIPTIONS["container:mp4kv2-panel-minio:9001/tcp"] == "Веб-консоль MinIO (mp4k_v2)"
    assert "web:https://portainer.test:9443" not in DEFAULT_DESCRIPTIONS


def test_tls_ports():
    assert TLS_PORTS == frozenset({443, 8443, 9443})
