import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from links_dashboard.config import DEFAULT_DESCRIPTIONS
from links_dashboard.discovery import ProjectInfo
from links_dashboard.models import CheckTarget, Endpoint, Override
from links_dashboard.store import State

logger = logging.getLogger(__name__)

STATUS_ORDER = ("up", "down", "na", "missing")
NO_GROUP = ""
Place = tuple[str, str | None]


@dataclass(frozen=True)
class Entry:
    endpoint: Endpoint
    cached: bool = False
    forced_status: str | None = None


@dataclass(frozen=True)
class TreeNode:
    group: str
    subgroup: str | None
    count: int
    new_count: int


@dataclass(frozen=True)
class ItemView:
    key: str
    kind: str
    label: str
    url: str | None
    source: str
    group: str
    subgroup: str | None
    reachable_from_mac: bool
    title: str | None
    description: str | None
    login_hint: str | None
    hidden: bool
    status: str
    is_new: bool
    cached: bool
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GroupView:
    project: ProjectInfo | None
    note: str
    items: list[ItemView]
    hidden: list[ItemView]


def place_of(endpoint: Endpoint, override: Override | None) -> Place:
    """Group and subgroup after the owner's override; an overridden group carries its own subgroup."""
    if override is not None and override.group is not None:
        group, subgroup = override.group, override.subgroup
    else:
        group, subgroup = endpoint.group, endpoint.subgroup
    if not group:
        return NO_GROUP, None
    return group, subgroup or None


def note_scope(group: str, subgroup: str | None) -> str:
    return f"{group}/{subgroup}" if subgroup else group


def restore_endpoint(key: str, data: dict[str, Any]) -> Endpoint | None:
    try:
        return Endpoint(**{**data, "check": CheckTarget(**data["check"])})
    except (KeyError, TypeError) as error:
        logger.warning("skipping unreadable remembered item %s: %s", key, error)
        return None


def kept_entries(state: State, source: str, present: set[str]) -> list[Entry]:
    """Remembered items of a failed source, shown as not answering until the source is back."""
    restored = [
        restore_endpoint(key, data)
        for key, data in state.known.items()
        if key not in present and data.get("source") == source
    ]
    return [
        Entry(endpoint, forced_status="down" if endpoint.reachable_from_mac else "na")
        for endpoint in restored
        if endpoint is not None
    ]


def with_missing(entries: list[Entry], state: State) -> list[Entry]:
    """Add remembered items that carry an owner override but are gone from every source."""
    present = {entry.endpoint.key for entry in entries}
    restored = [
        restore_endpoint(key, state.known[key])
        for key in state.overrides
        if key not in present and key in state.known
    ]
    missing = [Entry(endpoint, forced_status="missing") for endpoint in restored if endpoint is not None]
    return [*entries, *missing]


def entry_place(entry: Entry, state: State) -> Place:
    return place_of(entry.endpoint, state.overrides.get(entry.endpoint.key))


def is_hidden(entry: Entry, state: State) -> bool:
    override = state.overrides.get(entry.endpoint.key)
    return override is not None and override.hidden


def build_tree(entries: list[Entry], state: State) -> list[TreeNode]:
    """Tree nodes: "Без группы" first, then the owner's groups, then groups found by discovery."""
    counts: dict[Place, tuple[int, int]] = {}
    for entry in entries:
        if is_hidden(entry, state):
            continue
        where = entry_place(entry, state)
        count, new_count = counts.get(where, (0, 0))
        counts[where] = (count + 1, new_count + int(entry.endpoint.key not in state.seen))
    known_places = [(NO_GROUP, None), *state.groups]
    extra = sorted((p for p in counts if p not in known_places), key=lambda p: (p[0], p[1] or ""))
    return [
        TreeNode(group, subgroup, *counts.get((group, subgroup), (0, 0)))
        for group, subgroup in [*dict.fromkeys(known_places), *extra]
    ]


def item_view(entry: Entry, state: State, status: str) -> ItemView:
    endpoint = entry.endpoint
    override = state.overrides.get(endpoint.key) or Override()
    group, subgroup = place_of(endpoint, override)
    description = override.description
    return ItemView(
        key=endpoint.key,
        kind=override.kind or endpoint.kind,
        label=endpoint.label,
        url=endpoint.url,
        source=endpoint.source,
        group=group,
        subgroup=subgroup,
        reachable_from_mac=endpoint.reachable_from_mac,
        title=override.title,
        description=description if description is not None else DEFAULT_DESCRIPTIONS.get(endpoint.key),
        login_hint=override.login_hint,
        hidden=override.hidden,
        status=status,
        is_new=endpoint.key not in state.seen,
        cached=entry.cached,
        details=dict(endpoint.details),
    )


def sorted_items(items: list[ItemView]) -> list[ItemView]:
    return sorted(items, key=lambda item: (STATUS_ORDER.index(item.status), item.label))


def snapshot_payload(snapshot: Any, purposes: dict[str, str]) -> dict[str, Any]:
    """Serialise a snapshot, adding the owner's «Для чего» text to each forward row."""
    payload = asdict(snapshot)
    health = payload["health"]
    forwards = [{**row, "purpose": purposes.get(row["name"], "")} for row in health["forwards"]]
    return {**payload, "health": {**health, "forwards": forwards}}
