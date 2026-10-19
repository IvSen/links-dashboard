import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from links_dashboard.parsers import Forward, SyncSession, parse_forwards, parse_hosts, parse_sync

SSH_CONNECT_TIMEOUT = 5
KNOWN_HOSTS_NAME = "known_hosts"
STDERR_LIMIT = 300
PARSE_ERRORS = (ValueError, KeyError, TypeError, AttributeError)


class MacUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class MacInfo:
    hosts: list[str] = field(default_factory=list)
    sync: list[SyncSession] = field(default_factory=list)
    forwards: list[Forward] = field(default_factory=list)
    branches: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


Runner = Callable[[list[str], float], Awaitable[RunResult]]


async def run_subprocess(argv: list[str], timeout: float) -> RunResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    return RunResult(process.returncode or 0, stdout, stderr)


def build_ssh_argv(host: str, user: str, key_path: Path, known_hosts: Path) -> list[str]:
    return [
        "ssh",
        "-i",
        str(key_path),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        f"{user}@{host}",
    ]


def _decode_payload(stdout: bytes) -> dict:
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except ValueError as error:
        raise MacUnavailable(f"invalid response from the Mac: {error}") from error
    if not isinstance(payload, dict):
        raise MacUnavailable("invalid response from the Mac: not an object")
    return payload


def _str_dict(value: object, name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return {str(key): str(item) for key, item in value.items()}


def _list_or_empty(value: object, name: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"{name} must be a list of objects")
    return value


def _build_info(payload: dict) -> MacInfo:
    hosts = payload["hosts"]
    if not isinstance(hosts, str):
        raise TypeError("hosts must be a string")
    return MacInfo(
        hosts=parse_hosts(hosts),
        sync=parse_sync(_list_or_empty(payload.get("sync"), "sync")),
        forwards=parse_forwards(_list_or_empty(payload.get("forward"), "forward")),
        branches=_str_dict(payload.get("branches", {}), "branches"),
        errors=_str_dict(payload.get("errors", {}), "errors"),
    )


def _failure_reason(result: RunResult) -> str:
    stderr = result.stderr.decode("utf-8", errors="replace").strip()[:STDERR_LIMIT]
    base = f"ssh exited with code {result.returncode}"
    return f"{base}: {stderr}" if stderr else base


async def fetch_mac_info(
    host: str,
    user: str,
    key_path: Path,
    timeout: float = 8.0,
    *,
    known_hosts: Path | None = None,
    runner: Runner = run_subprocess,
) -> MacInfo:
    known = known_hosts if known_hosts is not None else key_path.with_name(KNOWN_HOSTS_NAME)
    argv = build_ssh_argv(host, user, key_path, known)
    try:
        result = await runner(argv, timeout)
    except TimeoutError as error:
        raise MacUnavailable(f"ssh timed out after {timeout:g}s") from error
    except OSError as error:
        raise MacUnavailable(f"cannot run ssh: {error}") from error
    if result.returncode != 0:
        raise MacUnavailable(_failure_reason(result))
    payload = _decode_payload(result.stdout)
    try:
        return _build_info(payload)
    except PARSE_ERRORS as error:
        detail = f"{type(error).__name__}: {error}"
        raise MacUnavailable(f"unexpected response from the Mac: {detail}") from error
