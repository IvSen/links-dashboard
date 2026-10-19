import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from links_dashboard.mac_source import MacInfo, MacUnavailable
from links_dashboard.parsers import Forward, parse_forward_config, parse_hosts

logger = logging.getLogger(__name__)

HOSTS_FILE = "hosts"
PROJECT_FILES = "*.mutagen.yml"
SSH_ERROR_KEY = "ssh"
FORWARD_ERROR_KEY = "forward"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_forwards(directory: Path) -> tuple[list[Forward], list[str]]:
    forwards: list[Forward] = []
    problems: list[str] = []
    for path in sorted(directory.glob(PROJECT_FILES)):
        try:
            forwards.extend(parse_forward_config(_read_text(path)))
        except (OSError, ValueError) as error:
            logger.warning("skipping synced Mutagen project file %s: %s", path, error)
            problems.append(f"{path.name}: {error}")
    return forwards, problems


def read_mac_files(directory: Path, ssh_reason: str) -> MacInfo:
    """Mac data from files Mutagen copies to the laptop: hosts and configured forwards, no live status."""
    try:
        hosts = parse_hosts(_read_text(directory / HOSTS_FILE))
    except OSError as error:
        raise MacUnavailable(f"{ssh_reason}; no synced hosts file: {error}") from error
    forwards, problems = _read_forwards(directory)
    errors = {SSH_ERROR_KEY: ssh_reason}
    if problems:
        errors[FORWARD_ERROR_KEY] = "; ".join(problems)
    return MacInfo(hosts=hosts, forwards=forwards, errors=errors, live=False)


async def with_file_fallback(fetch: Callable[[], Awaitable[MacInfo]], directory: Path) -> MacInfo:
    """Ask the Mac over SSH; when it does not answer, fall back to the synced files."""
    try:
        return await fetch()
    except MacUnavailable as error:
        logger.info("Mac over SSH unavailable (%s), reading synced files", error.reason)
        return await asyncio.to_thread(read_mac_files, directory, error.reason)
