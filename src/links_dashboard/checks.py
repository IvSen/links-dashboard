import asyncio
from typing import Literal

import httpx

from links_dashboard.models import CheckTarget

Status = Literal["up", "down", "na"]
SERVER_ERROR_FLOOR = 500


async def check(target: CheckTarget, timeout: float = 3.0) -> Status:
    if target.mode == "none":
        return "na"
    try:
        async with asyncio.timeout(timeout):
            return await _dispatch(target, timeout)
    except (TimeoutError, OSError, httpx.HTTPError):
        return "down"


async def _dispatch(target: CheckTarget, timeout: float) -> Status:
    if target.mode == "tcp":
        return await _check_tcp(target)
    return await _check_http(target, timeout)


async def _check_tcp(target: CheckTarget) -> Status:
    _, writer = await asyncio.open_connection(target.host, target.port)
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return "up"


def _request_parts(target: CheckTarget) -> tuple[str, dict[str, str], dict[str, str]]:
    scheme = "https" if target.mode == "https_sni" else "http"
    url = f"{scheme}://{target.host}:{target.port}/"
    if target.server_name is None:
        return url, {}, {}
    extensions = {"sni_hostname": target.server_name} if scheme == "https" else {}
    return url, {"Host": target.server_name}, extensions


async def _check_http(target: CheckTarget, timeout: float) -> Status:
    url, headers, extensions = _request_parts(target)
    async with httpx.AsyncClient(verify=False, timeout=timeout, follow_redirects=False) as client:
        response = await client.get(url, headers=headers, extensions=extensions)
    return "down" if response.status_code >= SERVER_ERROR_FLOOR else "up"


async def check_many(targets: dict[str, CheckTarget], limit: int = 20) -> dict[str, str]:
    semaphore = asyncio.Semaphore(limit)

    async def run(target: CheckTarget) -> Status:
        async with semaphore:
            return await check(target)

    results = await asyncio.gather(*(run(target) for target in targets.values()))
    return dict(zip(targets.keys(), results))
