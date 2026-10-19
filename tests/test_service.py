import asyncio
import threading

import pytest

from links_dashboard.fake import fake_sources
from links_dashboard.service import DashboardService
from links_dashboard.store import State, StateStore


class SlowStore(StateStore):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.started = threading.Event()
        self.release = threading.Event()

    def save(self, state: State) -> None:
        self.started.set()
        self.release.wait(5)
        super().save(state)


async def test_cancelled_mutation_keeps_disk_and_memory_in_sync(tmp_path):
    store = SlowStore(tmp_path / "state.json")
    service = DashboardService(None, fake_sources(), store)
    task = asyncio.create_task(service.set_note("first", "one"))
    await asyncio.to_thread(store.started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    store.release.set()
    await service.set_note("second", "two")
    expected = {"first": "one", "second": "two"}
    assert service._current_state().notes == expected
    assert StateStore(tmp_path / "state.json").load().notes == expected
