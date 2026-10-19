import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from links_dashboard.models import Endpoint, Override

INITIAL_GROUPS: tuple[tuple[str, str | None], ...] = (
    ("tools", None),
    ("cd_traffic", "kvs"),
    ("cd_traffic", "mp4k_v2"),
    ("cd_traffic", "content-panel"),
    ("carbox", "rosfines-dev"),
)


def _initial_groups() -> list[tuple[str, str | None]]:
    return list(INITIAL_GROUPS)


@dataclass(frozen=True)
class State:
    overrides: dict[str, Override] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    groups: list[tuple[str, str | None]] = field(default_factory=_initial_groups)
    seen: set[str] = field(default_factory=set)
    known: dict[str, dict] = field(default_factory=dict)
    cached_hosts: list[str] = field(default_factory=list)
    forward_purpose: dict[str, str] = field(default_factory=dict)

    def set_override(self, key: str, **fields: Any) -> "State":
        current = self.overrides.get(key, Override())
        return replace(self, overrides={**self.overrides, key: replace(current, **fields)})

    def set_note(self, scope: str, text: str) -> "State":
        return replace(self, notes={**self.notes, scope: text})

    def add_group(self, group: str, subgroup: str | None) -> "State":
        entry = (group, subgroup)
        if entry in self.groups:
            return self
        return replace(self, groups=[*self.groups, entry])

    def mark_seen(self, keys: Iterable[str]) -> "State":
        return replace(self, seen=self.seen | set(keys))

    def remember(self, endpoints: list[Endpoint]) -> "State":
        return replace(self, known={**self.known, **{e.key: asdict(e) for e in endpoints}})

    def set_forward_purpose(self, name: str, text: str) -> "State":
        return replace(self, forward_purpose={**self.forward_purpose, name: text})


def state_to_json(state: State) -> dict[str, Any]:
    return {
        "overrides": {key: asdict(value) for key, value in state.overrides.items()},
        "notes": dict(state.notes),
        "groups": [list(entry) for entry in state.groups],
        "seen": sorted(state.seen),
        "known": dict(state.known),
        "cached_hosts": list(state.cached_hosts),
        "forward_purpose": dict(state.forward_purpose),
    }


def state_from_json(data: dict[str, Any]) -> State:
    return State(
        overrides={key: Override(**value) for key, value in data["overrides"].items()},
        notes=dict(data["notes"]),
        groups=[(group, subgroup) for group, subgroup in data["groups"]],
        seen=set(data["seen"]),
        known=dict(data["known"]),
        cached_hosts=list(data["cached_hosts"]),
        forward_purpose=dict(data["forward_purpose"]),
    )


class StateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> State:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return State()
        try:
            return state_from_json(json.loads(raw))
        except (ValueError, KeyError, TypeError, AttributeError):
            self._set_corrupt_aside()
            return State()

    def save(self, state: State) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state_to_json(state), ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=self._path.parent, prefix=self._path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _set_corrupt_aside(self) -> None:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        self._path.rename(self._path.with_name(f"{self._path.name}.corrupt-{stamp}"))
