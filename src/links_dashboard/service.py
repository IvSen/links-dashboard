import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from typing import Any

from links_dashboard.checks import check_many
from links_dashboard.config import EDGE_CONTAINER, EDGE_HTTP_LISTEN, EDGE_TLS_LISTEN, Settings
from links_dashboard.discovery import ProjectInfo, build_endpoints, build_projects
from links_dashboard.health import Health, build_health
from links_dashboard.models import CheckTarget, Endpoint, Override
from links_dashboard.parsers import EdgeRoutes, Forward
from links_dashboard.sources import Fetched, Sources, fetch_all
from links_dashboard.store import State, StateStore
from links_dashboard.views import (
    NO_GROUP,
    Entry,
    GroupView,
    TreeNode,
    build_tree,
    entry_place,
    is_hidden,
    item_view,
    kept_entries,
    note_scope,
    sorted_items,
    with_missing,
)

__all__ = ["DashboardService", "Snapshot", "Sources", "UnknownItem"]

logger = logging.getLogger(__name__)

Checker = Callable[[dict[str, CheckTarget]], Awaitable[dict[str, str]]]
PATCH_FIELDS = frozenset(item.name for item in fields(Override))
KEPT_ON_FAILURE = (("cluster", "cluster"), ("docker", "container"))
EDGE_FALLBACK = EdgeRoutes(
    http_listen=EDGE_HTTP_LISTEN, tls_listen=EDGE_TLS_LISTEN, http=[], tls=[], http_default=0, tls_default=0
)


class UnknownItem(Exception):
    pass


@dataclass(frozen=True)
class Snapshot:
    tree: list[TreeNode]
    health: Health
    checked_at: str
    failed_sources: dict[str, str]


@dataclass(frozen=True)
class Discovery:
    endpoints: list[Endpoint]
    entries: list[Entry]
    projects: list[ProjectInfo]
    health: Health
    checked_at: str
    failed_sources: dict[str, str]


class DashboardService:
    def __init__(
        self, settings: Settings, sources: Sources, store: StateStore, checker: Checker | None = None
    ) -> None:
        self._settings = settings
        self._sources = sources
        self._store = store
        self._checker = checker or check_many
        self._refresh_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._inflight: asyncio.Task[Snapshot] | None = None
        self._state: State | None = None
        self._discovery: Discovery | None = None
        self._last_forwards: list[Forward] = []
        self._last_edge: EdgeRoutes | None = None

    async def refresh(self) -> Snapshot:
        """Run discovery; concurrent callers share the one discovery already in flight."""
        async with self._refresh_lock:
            if self._inflight is None or self._inflight.done():
                self._inflight = asyncio.create_task(self._run_discovery())
            task = self._inflight
        return await asyncio.shield(task)

    def snapshot(self) -> Snapshot | None:
        discovery = self._discovery
        if discovery is None:
            return None
        state = self._current_state()
        tree = build_tree(with_missing(discovery.entries, state), state)
        return Snapshot(tree, discovery.health, discovery.checked_at, dict(discovery.failed_sources))

    def forward_purposes(self) -> dict[str, str]:
        return dict(self._current_state().forward_purpose)

    async def group_view(self, group: str, subgroup: str | None) -> GroupView:
        if self._discovery is None:
            await self.refresh()
        discovery = self._discovery
        state = self._current_state()
        wanted = (group, subgroup or None) if group else (NO_GROUP, None)
        placed = [e for e in with_missing(discovery.entries, state) if entry_place(e, state) == wanted]
        visible = [entry for entry in placed if not is_hidden(entry, state)]
        targets = {e.endpoint.key: e.endpoint.check for e in visible if e.forced_status is None}
        statuses = await self._checker(targets)
        items = [
            item_view(entry, state, entry.forced_status or statuses.get(entry.endpoint.key, "down"))
            for entry in visible
        ]
        hidden = [
            item_view(entry, state, entry.forced_status or "na")
            for entry in placed
            if is_hidden(entry, state)
        ]
        project = next((p for p in discovery.projects if (p.group, p.subgroup) == wanted), None)
        return GroupView(
            project=project,
            note=state.notes.get(note_scope(*wanted), ""),
            items=sorted_items(items),
            hidden=sorted_items(hidden),
        )

    async def update_item(self, key: str, patch: dict[str, Any]) -> None:
        unknown = sorted(set(patch) - PATCH_FIELDS)
        if unknown:
            raise ValueError(f"unknown fields: {', '.join(unknown)}")

        def change(state: State) -> State:
            if key not in state.known:
                raise UnknownItem(key)
            return state.set_override(key, **patch)

        await self._mutate(change)

    async def set_note(self, scope: str, text: str) -> None:
        await self._mutate(lambda state: state.set_note(scope, text))

    async def add_group(self, group: str, subgroup: str | None) -> None:
        await self._mutate(lambda state: state.add_group(group, subgroup or None))

    async def mark_seen(self, keys: Iterable[str]) -> None:
        wanted = list(keys)
        await self._mutate(lambda state: state.mark_seen(wanted))

    async def set_forward_purpose(self, name: str, text: str) -> None:
        await self._mutate(lambda state: state.set_forward_purpose(name, text))

    def _current_state(self) -> State:
        if self._state is None:
            self._state = self._store.load()
        return self._state

    async def _mutate(self, change: Callable[[State], State], *, strict: bool = True) -> State:
        """Apply a change under the state lock and save it atomically; strict changes fail on I/O errors."""
        async with self._state_lock:
            updated = change(self._current_state())
            try:
                await asyncio.to_thread(self._store.save, updated)
            except OSError:
                logger.exception("could not save the state file")
                if strict:
                    raise
            self._state = updated
            return updated

    async def _run_discovery(self) -> Snapshot:
        fetched = await fetch_all(self._sources)
        discovery = self._build(fetched, self._current_state())

        def change(state: State) -> State:
            remembered = state.remember(discovery.endpoints)
            if fetched.mac is None:
                return remembered
            return replace(remembered, cached_hosts=list(fetched.mac.hosts))

        await self._mutate(change, strict=False)
        self._discovery = discovery
        return self.snapshot()

    def _inputs(self, fetched: Fetched, state: State) -> tuple[list[str], list[Forward], EdgeRoutes]:
        if fetched.mac is not None:
            self._last_forwards = list(fetched.mac.forwards)
        if fetched.edge is not None:
            self._last_edge = fetched.edge
        hosts = list(fetched.mac.hosts) if fetched.mac is not None else list(state.cached_hosts)
        return hosts, list(self._last_forwards), self._last_edge or EDGE_FALLBACK

    def _build(self, fetched: Fetched, state: State) -> Discovery:
        hosts, forwards, edge = self._inputs(fetched, state)
        containers = fetched.containers or []
        endpoints = build_endpoints(hosts, containers, fetched.ingresses or [], edge, forwards)
        mac_cached = fetched.mac is None
        fresh = [Entry(e, cached=mac_cached and e.source == "hosts") for e in endpoints]
        present = {endpoint.key for endpoint in endpoints}
        kept = [
            entry
            for failed_name, source in KEPT_ON_FAILURE
            if failed_name in fetched.failed
            for entry in kept_entries(state, source, present)
        ]
        edge_container = next((c for c in containers if c.name == EDGE_CONTAINER), None)
        health = build_health(
            fetched.mac, fetched.failed.get("mac"), edge_container, fetched.edge, fetched.laptop,
            state.forward_purpose,
        )
        return Discovery(
            endpoints=endpoints,
            entries=[*fresh, *kept],
            projects=build_projects(containers, fetched.mac.branches if fetched.mac else {}),
            health=health,
            checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
            failed_sources=dict(fetched.failed),
        )
