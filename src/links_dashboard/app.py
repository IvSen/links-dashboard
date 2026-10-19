import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from links_dashboard.config import Settings
from links_dashboard.service import Checker, DashboardService, UnknownItem
from links_dashboard.sources import Sources, real_sources
from links_dashboard.store import StateStore
from links_dashboard.views import snapshot_payload

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
PUBLIC_HOST = "links.test"
NAME_LIMIT = 200
TEXT_LIMIT = 20_000
OK = {"ok": True}


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemPatch(StrictBody):
    title: str | None = Field(default=None, max_length=NAME_LIMIT)
    description: str | None = Field(default=None, max_length=TEXT_LIMIT)
    login_hint: str | None = Field(default=None, max_length=NAME_LIMIT)
    group: str | None = Field(default=None, max_length=NAME_LIMIT)
    subgroup: str | None = Field(default=None, max_length=NAME_LIMIT)
    kind: Literal["web", "conn"] | None = None
    hidden: bool = False


class NoteBody(StrictBody):
    scope: str = Field(max_length=2 * NAME_LIMIT)
    text: str = Field(max_length=TEXT_LIMIT)


class GroupBody(StrictBody):
    group: str = Field(min_length=1, max_length=NAME_LIMIT)
    subgroup: str | None = Field(default=None, max_length=NAME_LIMIT)


class SeenBody(StrictBody):
    keys: list[str] = Field(max_length=5_000)


class PurposeBody(StrictBody):
    name: str = Field(min_length=1, max_length=NAME_LIMIT)
    text: str = Field(max_length=NAME_LIMIT)


def allowed_hosts(port: int) -> frozenset[str]:
    return frozenset({PUBLIC_HOST, f"127.0.0.1:{port}", f"localhost:{port}"})


def _install_host_guard(app: FastAPI, hosts: frozenset[str]) -> None:
    @app.middleware("http")
    async def host_guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        host = request.headers.get("host", "").lower()
        if host not in hosts:
            logger.warning("rejected request for host %r", host)
            return JSONResponse({"detail": "Доступ запрещён"}, status_code=403)
        return await call_next(request)


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(OSError)
    async def state_io_error(request: Request, error: OSError) -> JSONResponse:
        logger.error("request %s %s failed on state I/O: %s", request.method, request.url.path, error)
        return JSONResponse({"detail": "Не удалось сохранить состояние"}, status_code=500)


def _install_pages(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="Страница ещё не собрана")
        return FileResponse(page)


def _install_reads(app: FastAPI, service: DashboardService) -> None:
    @app.post("/api/refresh")
    async def refresh() -> dict[str, Any]:
        return snapshot_payload(await service.refresh(), service.forward_purposes())

    @app.get("/api/snapshot")
    async def snapshot() -> dict[str, Any]:
        current = service.snapshot() or await service.refresh()
        return snapshot_payload(current, service.forward_purposes())

    @app.get("/api/group")
    async def group(g: str = "", sg: str | None = None) -> dict[str, Any]:
        return asdict(await service.group_view(g, sg))


def _install_writes(app: FastAPI, service: DashboardService) -> None:
    @app.patch("/api/items/{key:path}")
    async def patch_item(key: str, patch: ItemPatch) -> dict[str, bool]:
        try:
            await service.update_item(key, patch.model_dump(exclude_unset=True))
        except UnknownItem as error:
            raise HTTPException(status_code=404, detail=f"Неизвестный адрес: {key}") from error
        return OK

    @app.put("/api/notes")
    async def put_note(body: NoteBody) -> dict[str, bool]:
        await service.set_note(body.scope, body.text)
        return OK

    @app.post("/api/groups")
    async def post_group(body: GroupBody) -> dict[str, bool]:
        await service.add_group(body.group, body.subgroup)
        return OK

    @app.post("/api/seen")
    async def post_seen(body: SeenBody) -> dict[str, bool]:
        await service.mark_seen(body.keys)
        return OK

    @app.put("/api/forward-purpose")
    async def put_purpose(body: PurposeBody) -> dict[str, bool]:
        await service.set_forward_purpose(body.name, body.text)
        return OK


def create_app(
    settings: Settings | None = None,
    sources: Sources | None = None,
    store: StateStore | None = None,
    checker: Checker | None = None,
) -> FastAPI:
    """Build the app; real sources are only wired, nothing touches the network until a request."""
    resolved = settings or Settings.from_env()
    service = DashboardService(
        resolved,
        sources or real_sources(resolved),
        store or StateStore(resolved.state),
        checker,
    )
    app = FastAPI(title="Links Dashboard")
    app.state.service = service
    _install_host_guard(app, allowed_hosts(resolved.port))
    _install_error_handlers(app)
    _install_pages(app)
    _install_reads(app, service)
    _install_writes(app, service)
    return app


def app_from_env() -> FastAPI:
    """The served app; LD_FAKE=1 wires fixture sources and a no-network checker for a local look."""
    if os.environ.get("LD_FAKE") != "1":
        return create_app()
    from links_dashboard.fake import failing_from_env, fake_checker, fake_settings, fake_sources

    settings = fake_settings()
    logger.warning("LD_FAKE=1: serving fixture data, state in %s", settings.state)
    return create_app(settings, sources=fake_sources(failing=failing_from_env()), checker=fake_checker)


app = app_from_env()
