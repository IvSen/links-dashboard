import json
from pathlib import Path

from links_dashboard.models import CheckTarget, Endpoint, Override
from links_dashboard.store import StateStore

INITIAL_GROUPS = [
    ("tools", None),
    ("cd_traffic", "kvs"),
    ("cd_traffic", "mp4k_v2"),
    ("cd_traffic", "content-panel"),
    ("carbox", "rosfines-dev"),
]


def make_endpoint(key: str = "web:https://vip4k.com.local") -> Endpoint:
    return Endpoint(
        key=key,
        kind="web",
        label="vip4k",
        url="https://vip4k.com.local",
        source="hosts",
        group="cd_traffic",
        subgroup="kvs",
        reachable_from_mac=True,
        check=CheckTarget(mode="https_sni", host="10.0.0.5", port=443, server_name="vip4k.com.local"),
        details={"container": "kvs-nginx"},
    )


def test_missing_file_gives_initial_groups(tmp_path: Path):
    state = StateStore(tmp_path / "s.json").load()

    assert state.groups == INITIAL_GROUPS
    assert state.overrides == {}
    assert state.notes == {}
    assert state.seen == set()
    assert state.known == {}
    assert state.cached_hosts == []
    assert state.forward_purpose == {}


def test_roundtrip_keeps_overrides_notes_seen(tmp_path: Path):
    store = StateStore(tmp_path / "s.json")
    state = (
        store.load()
        .set_override("web:https://vip4k.com.local", title="Админка", hidden=True)
        .set_note("cd_traffic/kvs", "admin / admin\n")
        .mark_seen({"web:https://vip4k.com.local"})
        .add_group("extra", "sub")
        .remember([make_endpoint()])
        .set_forward_purpose("pg", "База")
    )

    store.save(state)
    loaded = store.load()

    assert loaded == state
    assert loaded.overrides["web:https://vip4k.com.local"] == Override(title="Админка", hidden=True)
    assert loaded.notes == {"cd_traffic/kvs": "admin / admin\n"}
    assert loaded.seen == {"web:https://vip4k.com.local"}
    assert ("extra", "sub") in loaded.groups
    assert loaded.known["web:https://vip4k.com.local"]["label"] == "vip4k"
    assert loaded.forward_purpose == {"pg": "База"}


def test_helpers_do_not_mutate(tmp_path: Path):
    state = StateStore(tmp_path / "s.json").load()

    with_note = state.set_note("x", "y")
    with_override = state.set_override("k", title="t")
    with_group = state.add_group("g", None)
    with_seen = state.mark_seen(["k"])
    with_known = state.remember([make_endpoint()])
    with_purpose = state.set_forward_purpose("n", "t")

    assert "x" not in state.notes and with_note.notes == {"x": "y"}
    assert "k" not in state.overrides and "k" in with_override.overrides
    assert ("g", None) not in state.groups and ("g", None) in with_group.groups
    assert state.seen == set() and with_seen.seen == {"k"}
    assert state.known == {} and "web:https://vip4k.com.local" in with_known.known
    assert state.forward_purpose == {} and with_purpose.forward_purpose == {"n": "t"}


def test_set_override_merges_fields_and_add_group_is_idempotent(tmp_path: Path):
    state = StateStore(tmp_path / "s.json").load()

    merged = state.set_override("k", title="a").set_override("k", description="b")
    twice = state.add_group("tools", None)

    assert merged.overrides["k"] == Override(title="a", description="b")
    assert twice.groups == state.groups


def test_save_is_atomic(tmp_path: Path):
    path = tmp_path / "s.json"
    store = StateStore(path)

    store.save(store.load().set_note("a", "b"))

    assert list(tmp_path.glob("*.tmp")) == []
    assert json.loads(path.read_text(encoding="utf-8"))["notes"] == {"a": "b"}


def test_corrupt_file_is_kept_aside(tmp_path: Path):
    path = tmp_path / "s.json"
    path.write_text("{broken", encoding="utf-8")

    state = StateStore(path).load()

    assert state.groups == INITIAL_GROUPS
    assert not path.exists()
    aside = list(tmp_path.glob("s.json.corrupt-*"))
    assert len(aside) == 1
    assert aside[0].read_text(encoding="utf-8") == "{broken"
