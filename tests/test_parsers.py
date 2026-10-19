import json
from pathlib import Path

import pytest

from links_dashboard.parsers import (
    parse_edge_conf,
    parse_forwards,
    parse_hosts,
    parse_sync,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _text(name: str) -> str:
    return (FIXTURES / name).read_text()


def _json(name: str) -> list[dict]:
    return json.loads(_text(name))


def test_hosts_strips_commas():
    text = "127.0.0.1 offer.vip4k.com.local, admin.vip4k.com.local"
    assert parse_hosts(text) == ["offer.vip4k.com.local", "admin.vip4k.com.local"]


def test_hosts_skips_foreign_ip_and_system_names():
    names = parse_hosts(_text("hosts.txt"))
    assert "admin.vip4k.com" not in names
    assert "localhost" not in names
    assert "broadcasthost" not in names
    assert "kubernetes.docker.internal" not in names
    assert "beszel.test" in names
    assert "netdata.test" in names


def test_hosts_dedupes_lowercases_and_skips_comments():
    text = "\n".join(
        [
            "# 127.0.0.1 commented.local",
            "127.0.0.1 A.Local b.local # trailing",
            "127.0.0.1\ta.local",
            "::1 localhost",
        ]
    )
    assert parse_hosts(text) == ["a.local", "b.local"]


def test_sync_fixture():
    sessions = parse_sync(_json("mutagen_sync.json"))
    assert len(sessions) == 4
    by_name = {s.name: s for s in sessions}
    assert set(by_name) == {"kvs", "mp4k-v2", "content-panel", "carbox"}
    kvs = by_name["kvs"]
    assert kvs.status_text == "следит за изменениями"
    assert kvs.files is not None and kvs.files > 0
    assert kvs.size_bytes is not None and kvs.size_bytes > 0
    assert kvs.path.endswith("kvs")
    assert kvs.ok is True


def _session(**overrides) -> dict:
    base = {
        "name": "s",
        "status": "watching",
        "paused": False,
        "alpha": {"path": "/p", "files": 5, "totalFileSize": 10},
        "beta": {"path": "/p"},
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("status", "text"),
    [
        ("watching", "следит за изменениями"),
        ("scanning", "сканирует"),
        ("staging-alpha", "передаёт файлы"),
        ("staging-beta", "передаёт файлы"),
        ("transitioning", "передаёт файлы"),
        ("saving", "передаёт файлы"),
        ("connecting-alpha", "нет связи"),
        ("connecting-beta", "нет связи"),
        ("disconnected", "нет связи"),
    ],
)
def test_sync_status_text(status, text):
    (session,) = parse_sync([_session(status=status)])
    assert session.status_text == text
    assert session.ok is (status == "watching")


def test_sync_paused_is_not_ok():
    (session,) = parse_sync([_session(paused=True)])
    assert session.paused is True
    assert session.status_text == "на паузе"
    assert session.ok is False


def test_sync_counts_conflicts_and_problems():
    raw = _session(
        conflicts=[{"root": "a"}, {"root": "b"}],
        transitionProblems=[{"path": "x"}],
        alpha={"path": "/p", "scanProblems": [{"path": "y"}]},
        beta={"path": "/p", "scanProblems": [{"path": "z"}, {"path": "w"}]},
    )
    (session,) = parse_sync([raw])
    assert session.conflicts == 2
    assert session.problems == 4
    assert session.files is None
    assert session.size_bytes is None
    assert session.ok is False


def test_forward_reverse_detected():
    forwards = {f.name: f for f in parse_forwards(_json("mutagen_forward.json"))}
    xdebug = forwards["xdebug"]
    assert xdebug.reverse is True
    assert xdebug.src_port == 9003
    assert xdebug.dest_port == 9003
    edge = forwards["edge-https"]
    assert edge.reverse is False
    assert edge.src_port == 443
    assert edge.dest_port == 10443
    assert edge.ok is True
    assert edge.source == "tcp:0.0.0.0:443"
    assert edge.destination == "winbox:tcp:127.0.0.1:10443"


def test_forward_unhealthy_and_paused():
    base = {
        "name": "f",
        "paused": False,
        "openConnections": 2,
        "source": {"protocol": "local", "endpoint": "tcp:localhost:1"},
        "destination": {"protocol": "ssh", "host": "winbox", "endpoint": "tcp:localhost:2"},
    }
    (down,) = parse_forwards([{**base, "status": "connecting-destination"}])
    assert down.ok is False
    assert down.status_text == "нет связи"
    assert down.open_connections == 2
    (paused,) = parse_forwards([{**base, "status": "forwarding", "paused": True}])
    assert paused.ok is False
    assert paused.status_text == "на паузе"


def test_forward_without_port():
    (fwd,) = parse_forwards(
        [
            {
                "name": "sock",
                "paused": False,
                "status": "forwarding",
                "source": {"protocol": "local", "endpoint": "unix:/tmp/a.sock"},
                "destination": {"protocol": "local", "endpoint": "unix:/tmp/b.sock"},
            }
        ]
    )
    assert fwd.src_port is None
    assert fwd.dest_port is None


def test_edge_routes():
    routes = parse_edge_conf(_text("edge-nginx.conf"))
    assert routes.http_listen == 10080
    assert routes.tls_listen == 10443
    assert routes.route_http("beszel.test") == 8095
    assert routes.route_http("netdata.test") == 19999
    assert routes.route_http("babylon.local.rf-tech.ru") == 80
    assert routes.route_http("vip4k.com.local") == 8080
    assert routes.route_tls("vip4k.com.local") == 8443
    assert routes.route_tls("babylon.local.rf-tech.ru") == 443
    assert routes.http_default == 8080
    assert routes.tls_default == 8443
    assert ("beszel.test", False, 8095) in routes.http
    assert (r"\.local\.rf-tech\.ru$", True, 80) in routes.http
    assert all(pattern != "default" for pattern, _, _ in routes.http)


def test_edge_conf_missing_blocks_raises():
    with pytest.raises(ValueError):
        parse_edge_conf("events {}")
