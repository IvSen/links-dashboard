from pathlib import Path

from links_dashboard.config import KNOWN_HOSTS, Settings


def test_defaults(monkeypatch):
    for name in ("LD_STATE", "LD_EDGE_CONF", "LD_KUBECONFIG", "LD_MAC_HOST", "LD_MAC_USER", "LD_MAC_KEY", "LD_PORT"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.state == Path("/data/state.json")
    assert settings.edge_conf == Path("/config/edge-nginx.conf")
    assert settings.kubeconfig == Path("/data/kubeconfig")
    assert settings.mac_host == "10.0.100.243"
    assert settings.mac_user == "i.senishin"
    assert settings.mac_key == Path("/data/mac_key")
    assert settings.port == 8099


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("LD_PORT", "9000")
    monkeypatch.setenv("LD_STATE", "/tmp/s.json")
    settings = Settings.from_env()
    assert settings.port == 9000
    assert settings.state == Path("/tmp/s.json")


def test_known_hosts():
    assert KNOWN_HOSTS == {"netdata.test": ("tools", None), "links.test": ("tools", None)}
