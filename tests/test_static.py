from fastapi.testclient import TestClient

from links_dashboard.app import app_from_env, create_app
from links_dashboard.config import Settings

HOST = {"Host": "links.test"}


def _settings(tmp_path) -> Settings:
    return Settings(
        state=tmp_path / "state.json",
        edge_conf=tmp_path / "edge.conf",
        kubeconfig=tmp_path / "kubeconfig",
        mac_host="mac.invalid",
        mac_user="user",
        mac_key=tmp_path / "mac_key",
        port=8099,
    )


def test_index_served(tmp_path):
    with TestClient(create_app(_settings(tmp_path)), headers=HOST) as client:
        response = client.get("/")
    assert response.status_code == 200
    for region in ('id="tree"', 'id="health"', 'id="project"'):
        assert region in response.text


def test_static_assets_served(tmp_path):
    with TestClient(create_app(_settings(tmp_path)), headers=HOST) as client:
        script = client.get("/static/app.js")
        styles = client.get("/static/styles.css")
    assert script.status_code == 200
    assert styles.status_code == 200


def test_fake_app_serves_fixture_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LD_FAKE", "1")
    monkeypatch.setenv("LD_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("LD_FAKE_FAIL", "cluster")
    with TestClient(app_from_env(), headers=HOST) as client:
        snapshot = client.post("/api/refresh").json()
        kvs = client.get("/api/group", params={"g": "cd_traffic", "sg": "kvs"}).json()
    assert snapshot["failed_sources"] == {"cluster": "connection refused"}
    assert any(node["subgroup"] == "kvs" and node["count"] > 0 for node in snapshot["tree"])
    assert kvs["project"]["stopped"] == ["kvs-redis"]
    assert {item["status"] for item in kvs["items"]} <= {"up", "down", "na", "missing"}
