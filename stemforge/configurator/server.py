"""FastAPI app + uvicorn entry point for the configurator HTTP server.

The single :data:`app` object is built by :func:`create_app` so tests
can construct fresh instances. :func:`run` is the console-script /
``tools.m4l_configurator_server`` entry point — picks a port, writes
``~/stemforge/.configurator_port`` for the strip device to discover, and
boots uvicorn on ``127.0.0.1``.

Routes (legacy):

- ``GET  /healthz``
- ``GET  /state``
- ``GET  /state/stream``
- ``GET  /preview/{clip_id}``
- ``POST /intent/load-manifest``
- ``POST /intent/commit``
- ``POST /intent/assign-pad``
- ``POST /intent/clear-pad``
- ``POST /intent/set-group-format``
- ``POST /intent/recompute``
- ``POST /intent/export``

Routes (Phase 1B — curation CRUD, spec §4.3):

- ``GET    /curations``
- ``POST   /curations``
- ``GET    /curations/{name}``
- ``POST   /curations/{name}/open``
- ``POST   /curations/{name}/save-as``
- ``DELETE /curations/{name}``
- ``PATCH  /curations/{name}/template``
- ``PATCH  /curations/{name}/target``
- ``POST   /curations/{name}/commit``

Plus a static-files mount on ``/`` (configurable static dir; defaults to
the package's ``static/`` directory). Lane B's frontend build output
lands there.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from stemforge.scene_model import Project

from . import intents
from .intents import (
    CommitCurationBody,
    CreateCurationBody,
    OpenCurationBody,
    PatchTargetBody,
    PatchTemplateBody,
    SaveAsBody,
)
from .preview import build_audio_response
from .schemas import (
    AssignPadRequest,
    ClearPadRequest,
    CommitRequest,
    Curation,
    ExportRequest,
    IntentResponse,
    LoadManifestRequest,
    RecomputeRequest,
    SetGroupFormatRequest,
)
from .state import AppState, SseEvent

DEFAULT_HOST = "127.0.0.1"
PORT_ENV = "STEMFORGE_CONFIGURATOR_PORT"
PORT_RANGE = range(7430, 7441)  # inclusive on 7440
PORT_FILE = Path.home() / "stemforge" / ".configurator_port"
STATIC_DIR_ENV = "STEMFORGE_CONFIGURATOR_STATIC"
DEFAULT_STATIC_DIR = Path(__file__).parent / "static"
CURATIONS_DIR_ENV = "STEMFORGE_CURATIONS_DIR"
STATE_FILE_ENV = "STEMFORGE_STATE_FILE"
PLACEHOLDER_HTML = (
    '<!doctype html><html><head><meta charset="utf-8">'
    "<title>StemForge Configurator</title></head><body>"
    "<h1>Configurator static files not built yet</h1>"
    "<p>Run <code>cd web/configurator && npm run build</code>.</p>"
    "</body></html>"
)


# ── App factory ──────────────────────────────────────────────────────────────


def create_app(
    *,
    static_dir: Path | None = None,
    curations_dir: Path | None = None,
    state_path: Path | None = None,
) -> FastAPI:
    """Construct a fresh :class:`FastAPI` app and bind an :class:`AppState`.

    Each call returns an independent app — tests use this to avoid
    state leakage between cases. Production callers should use the
    module-level :data:`app` built lazily by :func:`run`.

    ``curations_dir`` and ``state_path`` override the on-disk locations
    used by the new Phase 1B curation CRUD endpoints; tests point them
    at ``tmp_path`` to keep the user's real ``~/stemforge`` untouched.
    """
    state = AppState()
    resolved_curations = (
        Path(curations_dir).expanduser().resolve()
        if curations_dir is not None
        else (
            Path(os.environ[CURATIONS_DIR_ENV]).expanduser().resolve()
            if os.environ.get(CURATIONS_DIR_ENV)
            else state.curations_dir
        )
    )
    resolved_state_path = (
        Path(state_path).expanduser().resolve()
        if state_path is not None
        else (
            Path(os.environ[STATE_FILE_ENV]).expanduser().resolve()
            if os.environ.get(STATE_FILE_ENV)
            else state.state_path
        )
    )
    state.curations_dir = resolved_curations
    state.state_path = resolved_state_path

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # No teardown to do — the lock + subscriber list are GC'd when
        # the app dies.

    app = FastAPI(
        title="StemForge Configurator",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.configurator = state

    _register_routes(app, state)

    # Static mount: serve the popup's build output (or the placeholder)
    # at ``/``. Done last so explicit routes take precedence.
    resolved_static = _resolve_static_dir(static_dir)
    if not (resolved_static / "index.html").is_file():
        resolved_static.mkdir(parents=True, exist_ok=True)
        (resolved_static / "index.html").write_text(PLACEHOLDER_HTML)
    app.mount("/", StaticFiles(directory=str(resolved_static), html=True), name="static")

    return app


def _resolve_static_dir(override: Path | None) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    env = os.environ.get(STATIC_DIR_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_STATIC_DIR.resolve()


# ── Routes ───────────────────────────────────────────────────────────────────


def _register_routes(app: FastAPI, state: AppState) -> None:
    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "version": "0.2.0"})

    @app.get("/state")
    async def get_state() -> Project:
        return state.project

    @app.get("/state/stream")
    async def stream_state(request: Request) -> StreamingResponse:
        q = state.subscribe()

        async def event_source() -> AsyncIterator[bytes]:
            try:
                # Send the current state immediately so a fresh subscriber
                # has a baseline without waiting for the next mutation.
                snapshot = SseEvent(
                    event="state",
                    data=json.loads(state.project.model_dump_json(exclude_none=True)),
                )
                yield snapshot.to_wire().encode("utf-8")
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        # Keep-alive comment frame so intermediaries don't
                        # idle-kill the stream.
                        yield b": keepalive\n\n"
                        continue
                    yield event.to_wire().encode("utf-8")
            finally:
                state.unsubscribe(q)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    @app.get("/preview/{clip_id}")
    async def preview(
        clip_id: str,
        range: str | None = Header(default=None),  # noqa: A002
    ) -> Response:
        clip_path = _resolve_clip_path(state.project, clip_id)
        if clip_path is None:
            raise HTTPException(status_code=404, detail=f"clip not found: {clip_id}")
        return build_audio_response(clip_path, range_header=range)

    # ── Intent routes ────────────────────────────────────────────────────────

    @app.post("/intent/load-manifest", response_model=IntentResponse)
    async def post_load_manifest(req: LoadManifestRequest) -> IntentResponse:
        return await intents.handle_load_manifest(state, req)

    @app.post("/intent/commit", response_model=IntentResponse)
    async def post_commit(req: CommitRequest) -> IntentResponse:
        return await intents.handle_commit(state, req)

    @app.post("/intent/assign-pad", response_model=IntentResponse)
    async def post_assign_pad(req: AssignPadRequest) -> IntentResponse:
        return await intents.handle_assign_pad(state, req)

    @app.post("/intent/clear-pad", response_model=IntentResponse)
    async def post_clear_pad(req: ClearPadRequest) -> IntentResponse:
        return await intents.handle_clear_pad(state, req)

    @app.post("/intent/set-group-format", response_model=IntentResponse)
    async def post_set_group_format(req: SetGroupFormatRequest) -> IntentResponse:
        return await intents.handle_set_group_format(state, req)

    @app.post("/intent/recompute", response_model=IntentResponse)
    async def post_recompute(req: RecomputeRequest) -> IntentResponse:
        return await intents.handle_recompute(state, req)

    @app.post("/intent/export", response_model=IntentResponse)
    async def post_export(req: ExportRequest) -> IntentResponse:
        return await intents.handle_export(state, req)

    # ── Curation CRUD (Phase 1B, spec §4.3) ───────────────────────────────

    @app.get("/curations")
    async def list_curations_route() -> dict[str, Any]:
        return await intents.handle_list_curations(state)

    @app.post("/curations", response_model=Curation, status_code=201)
    async def create_curation_route(body: CreateCurationBody) -> Curation:
        return await intents.handle_create_curation(state, body)

    @app.get("/curations/{name}", response_model=Curation)
    async def get_curation_route(name: str) -> Curation:
        return await intents.handle_get_curation(state, name)

    @app.post("/curations/{name}/open")
    async def open_curation_route(name: str, body: OpenCurationBody) -> dict[str, Any]:
        return await intents.handle_open_curation(state, name, body)

    @app.post("/curations/{name}/save-as", response_model=Curation)
    async def save_as_route(name: str, body: SaveAsBody) -> Curation:
        return await intents.handle_save_as(state, name, body)

    @app.delete("/curations/{name}")
    async def delete_curation_route(name: str) -> dict[str, Any]:
        return await intents.handle_delete_curation(state, name)

    @app.patch("/curations/{name}/template", response_model=Curation)
    async def patch_template_route(name: str, body: PatchTemplateBody) -> Curation:
        return await intents.handle_patch_template(state, name, body)

    @app.patch("/curations/{name}/target", response_model=Curation)
    async def patch_target_route(name: str, body: PatchTargetBody) -> Curation:
        return await intents.handle_patch_target(state, name, body)

    @app.post("/curations/{name}/commit", response_model=Curation)
    async def commit_curation_route(name: str, body: CommitCurationBody) -> Curation:
        return await intents.handle_curation_commit(state, name, body)


def _resolve_clip_path(project: Project, clip_id: str) -> Path | None:
    """Find a clip with ``audio_hash == clip_id`` in the project; return its path."""
    for song in project.songs:
        for group in song.groups:
            for pad in group.pads:
                if pad.clip is None:
                    continue
                if pad.clip.audio_hash == clip_id and pad.clip.path:
                    p = Path(pad.clip.path).expanduser()
                    if p.is_file():
                        return p
    return None


# ── Port discovery ───────────────────────────────────────────────────────────


def discover_port() -> int:
    """Pick a port: env var → first free in :data:`PORT_RANGE`.

    Writes the resolved port to :data:`PORT_FILE` so the M4L strip device
    can discover it. Raises :class:`RuntimeError` when no free port is
    found in the configured range.
    """
    env = os.environ.get(PORT_ENV)
    if env:
        try:
            return int(env)
        except ValueError:
            pass  # fall through to scan

    for candidate in PORT_RANGE:
        if _port_free(candidate):
            return candidate
    raise RuntimeError(
        f"no free port in {PORT_RANGE.start}-{PORT_RANGE.stop - 1}; set {PORT_ENV} to override."
    )


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((DEFAULT_HOST, port))
        except OSError:
            return False
    return True


def write_port_file(port: int, path: Path | None = None) -> Path:
    """Persist the resolved port for the strip device to discover."""
    target = path or PORT_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(port))
    return target


# ── Module-level app (for uvicorn import-string startup) ─────────────────────


def _build_default_app() -> FastAPI:
    return create_app()


app: FastAPI = _build_default_app()


def run() -> None:
    """Console-script entry: pick port, write port file, run uvicorn."""
    import uvicorn

    port = discover_port()
    write_port_file(port)
    uvicorn.run(
        "stemforge.configurator.server:app",
        host=DEFAULT_HOST,
        port=port,
        log_level="info",
    )


__all__ = [
    "DEFAULT_HOST",
    "PORT_ENV",
    "PORT_FILE",
    "PORT_RANGE",
    "app",
    "create_app",
    "discover_port",
    "run",
    "write_port_file",
]
