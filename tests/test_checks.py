import asyncio
import ssl
from contextlib import asynccontextmanager

import pytest
import trustme

from links_dashboard.checks import check, check_many
from links_dashboard.models import CheckTarget


def _response(status: int) -> bytes:
    return f"HTTP/1.1 {status} X\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()


@asynccontextmanager
async def serve(handler, ssl_context=None):
    server = await asyncio.start_server(handler, "127.0.0.1", 0, ssl=ssl_context)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


def status_handler(status: int, seen: list[bytes] | None = None):
    async def handler(reader, writer):
        data = await reader.readuntil(b"\r\n\r\n")
        if seen is not None:
            seen.append(data)
        writer.write(_response(status))
        await writer.drain()
        writer.close()

    return handler


async def silent_handler(reader, writer):
    await asyncio.sleep(5)
    writer.close()


def web(port: int, server_name: str | None = None) -> CheckTarget:
    return CheckTarget("http", "127.0.0.1", port, server_name)


async def test_http_404_is_up():
    async with serve(status_handler(404)) as port:
        assert await check(web(port)) == "up"


async def test_http_redirect_is_up():
    async with serve(status_handler(302)) as port:
        assert await check(web(port)) == "up"


async def test_http_502_is_down():
    async with serve(status_handler(502)) as port:
        assert await check(web(port)) == "down"


async def test_http_sends_host_header():
    seen: list[bytes] = []
    async with serve(status_handler(200, seen)) as port:
        await check(web(port, "links.test"))
    assert b"host: links.test" in seen[0].lower()


async def test_refused_is_down():
    async with serve(status_handler(200)) as port:
        pass
    assert await check(web(port)) == "down"


async def test_timeout_is_down():
    async with serve(silent_handler) as port:
        assert await check(web(port), timeout=0.5) == "down"


async def test_tcp_up_and_down():
    async def handler(reader, writer):
        writer.close()

    async with serve(handler) as port:
        target = CheckTarget("tcp", "127.0.0.1", port, None)
        assert await check(target) == "up"
    assert await check(target) == "down"


async def test_none_mode_is_na():
    assert await check(CheckTarget("none", "127.0.0.1", 1, None)) == "na"


def _tls_server_context(seen_sni: list[str | None]) -> ssl.SSLContext:
    ca = trustme.CA()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ca.issue_cert("127.0.0.1").configure_cert(context)
    context.sni_callback = lambda sock, name, ctx: seen_sni.append(name)
    return context


async def test_sni_sent():
    seen_sni: list[str | None] = []
    seen_requests: list[bytes] = []
    context = _tls_server_context(seen_sni)
    async with serve(status_handler(200, seen_requests), context) as port:
        target = CheckTarget("https_sni", "127.0.0.1", port, "vip4k.com.local")
        assert await check(target) == "up"
    assert seen_sni == ["vip4k.com.local"]
    assert b"host: vip4k.com.local" in seen_requests[0].lower()


async def test_https_without_server_name():
    seen_sni: list[str | None] = []
    context = _tls_server_context(seen_sni)
    async with serve(status_handler(200), context) as port:
        target = CheckTarget("https_sni", "127.0.0.1", port, None)
        assert await check(target) == "up"


async def test_check_many_returns_per_key():
    async with serve(status_handler(200)) as ok_port, serve(status_handler(500)) as bad_port:
        targets = {
            "a": web(ok_port),
            "b": web(bad_port),
            "c": CheckTarget("none", "127.0.0.1", 1, None),
        }
        assert await check_many(targets, limit=2) == {"a": "up", "b": "down", "c": "na"}


async def test_check_many_bounds_concurrency():
    active = 0
    peak = 0

    async def handler(reader, writer):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await reader.readuntil(b"\r\n\r\n")
        await asyncio.sleep(0.05)
        writer.write(_response(200))
        await writer.drain()
        writer.close()
        active -= 1

    async with serve(handler) as port:
        targets = {str(i): web(port) for i in range(8)}
        result = await check_many(targets, limit=2)
    assert set(result.values()) == {"up"}
    assert peak <= 2
