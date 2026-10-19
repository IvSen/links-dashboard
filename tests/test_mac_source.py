import json
from pathlib import Path

import pytest

from links_dashboard.mac_source import MacUnavailable, RunResult, fetch_mac_info

FIXTURES = Path(__file__).parent / "fixtures"
KEY = Path("/data/mac_key")


def _payload(**overrides) -> dict:
    payload = {
        "generated_at": "2026-10-19T10:00:00+00:00",
        "hosts": (FIXTURES / "hosts.txt").read_text(),
        "sync": json.loads((FIXTURES / "mutagen_sync.json").read_text()),
        "forward": json.loads((FIXTURES / "mutagen_forward.json").read_text()),
        "branches": {"/Users/i.senishin/project/carbox/rosfines-dev": "main"},
        "errors": {},
    }
    return {**payload, **overrides}


def _runner(result: RunResult, calls: list | None = None):
    async def run(argv: list[str], timeout: float) -> RunResult:
        if calls is not None:
            calls.append((argv, timeout))
        return result

    return run


def _ok(payload: dict) -> RunResult:
    return RunResult(0, json.dumps(payload).encode(), b"")


async def test_fetch_parses_payload():
    info = await fetch_mac_info("10.0.100.243", "i.senishin", KEY, runner=_runner(_ok(_payload())))
    assert "vip4k.com.local" in info.hosts
    assert len(info.sync) == 4
    assert info.forwards
    assert info.branches == {"/Users/i.senishin/project/carbox/rosfines-dev": "main"}
    assert info.errors == {}


async def test_fetch_builds_restricted_ssh_command():
    calls: list = []
    await fetch_mac_info(
        "10.0.100.243", "i.senishin", KEY, timeout=5.0, runner=_runner(_ok(_payload()), calls)
    )
    argv, timeout = calls[0]
    assert argv[0] == "ssh"
    assert argv[argv.index("-i") + 1] == str(KEY)
    assert "BatchMode=yes" in argv
    assert "ConnectTimeout=5" in argv
    assert "StrictHostKeyChecking=accept-new" in argv
    assert f"UserKnownHostsFile={KEY.parent / 'known_hosts'}" in argv
    assert argv[-1] == "i.senishin@10.0.100.243"
    assert timeout == 5.0


async def test_fetch_null_sources_become_empty_with_errors():
    payload = _payload(sync=None, forward=None, errors={"sync": "boom", "forward": "boom2"})
    info = await fetch_mac_info("h", "u", KEY, runner=_runner(_ok(payload)))
    assert info.sync == []
    assert info.forwards == []
    assert info.errors == {"sync": "boom", "forward": "boom2"}


async def test_fetch_raises_on_ssh_failure():
    runner = _runner(RunResult(255, b"", b"Connection refused"))
    with pytest.raises(MacUnavailable) as caught:
        await fetch_mac_info("h", "u", KEY, runner=runner)
    assert "Connection refused" in caught.value.reason


async def test_fetch_raises_on_invalid_json():
    runner = _runner(RunResult(0, b"not json", b""))
    with pytest.raises(MacUnavailable):
        await fetch_mac_info("h", "u", KEY, runner=runner)


async def test_fetch_raises_on_timeout():
    async def run(argv: list[str], timeout: float) -> RunResult:
        raise TimeoutError

    with pytest.raises(MacUnavailable):
        await fetch_mac_info("h", "u", KEY, runner=run)


async def test_fetch_raises_when_ssh_binary_missing():
    async def run(argv: list[str], timeout: float) -> RunResult:
        raise FileNotFoundError("ssh")

    with pytest.raises(MacUnavailable):
        await fetch_mac_info("h", "u", KEY, runner=run)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        _payload(sync={"not": "a list"}),
        _payload(sync=[1, 2]),
        _payload(forward=["x"]),
        _payload(hosts=None),
        _payload(branches=[]),
        _payload(errors="oops"),
    ],
)
async def test_fetch_converts_any_shape_error(payload):
    with pytest.raises(MacUnavailable):
        await fetch_mac_info("h", "u", KEY, runner=_runner(_ok(payload)))
