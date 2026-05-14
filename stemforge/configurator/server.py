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

Routes (Phase 3A — config templates, spec §3.6 / §6.7):

- ``GET    /templates``

The PATCH ``/template`` endpoint above also fires a device notification
(``template-changed <group> <template-name>``) when a template assignment
changes, so the staging track hot-applies the rack without a full LOAD.

Routes (Phase 1.5 — forge endpoints + curation rename/close bridge):

- ``GET  /forges``
- ``POST /forges/{slug}/load``
- ``POST /forges/{slug}/unload``
- ``POST /forges/{slug}/re-anchor``
- ``POST /forges/{slug}/re-curate``
- ``POST /forges/{slug}/reveal``
- ``POST /curations/{name}/rename``
- ``POST /curations/active/close``

Routes (Phase 4A — active-curation persistence + device bootstrap):

- ``POST /als-opened``  (device → server on Live's ``loadbang``)

Routes (Phase 3C — EXPORT via server):

- ``POST /curations/{name}/export``
- ``POST /intent/pick-save-path``

Plus a static-files mount on ``/`` (configurable static dir; defaults to
the package's ``static/`` directory). Lane B's frontend build output
lands there.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stemforge.scene_model import Project

from . import intents
from .bounce_handler import BounceCompletion, BounceProgress
from .export_handler import (
    DEFAULT_TARGET_FORMAT,
    ExportValidationError,
    perform_export,
)
from .forge_io import default_processed_dir, list_forges, resolve_forge_dir
from .intents import (
    AlsOpenedBody,
    CloseActiveCurationBody,
    CreateCurationBody,
    DeviceCommitBody,
    OpenCurationBody,
    PatchTargetBody,
    PatchTemplateBody,
    RenameCurationBody,
    SaveAsBody,
    TriggerBounceBody,
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
from .template_io import default_templates_dir, list_templates

DEFAULT_HOST = "127.0.0.1"
PORT_ENV = "STEMFORGE_CONFIGURATOR_PORT"
PORT_RANGE = range(7430, 7441)  # inclusive on 7440
PORT_FILE = Path.home() / "stemforge" / ".configurator_port"
STATIC_DIR_ENV = "STEMFORGE_CONFIGURATOR_STATIC"
DEFAULT_STATIC_DIR = Path(__file__).parent / "static"
CURATIONS_DIR_ENV = "STEMFORGE_CURATIONS_DIR"
STATE_FILE_ENV = "STEMFORGE_STATE_FILE"
PROCESSED_DIR_ENV = "STEMFORGE_PROCESSED_DIR"
TEMPLATES_DIR_ENV = "STEMFORGE_TEMPLATES_DIR"
# Device-side ``[udpreceive]`` port — the strip device listens here for the
# server→device notifications used by Phase 3A (template hot-apply). Phase 2
# left no formalized reverse path, so we use UDP per the spec language
# ("if Phase 2 didn't formalize a reverse path, do `[udpsend localhost 7420
# template-changed <args>]`"). The patcher's `[udpreceive 7420]` already
# exists; this constant lets tests override.
DEVICE_UDP_PORT_ENV = "STEMFORGE_DEVICE_UDP_PORT"
DEFAULT_DEVICE_UDP_PORT = 7420
DEFAULT_DEVICE_UDP_HOST = "127.0.0.1"
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
    processed_dir: Path | None = None,
    templates_dir: Path | None = None,
    subprocess_runner: Any | None = None,
    device_notifier: Any | None = None,
) -> FastAPI:
    """Construct a fresh :class:`FastAPI` app and bind an :class:`AppState`.

    Each call returns an independent app — tests use this to avoid
    state leakage between cases. Production callers should use the
    module-level :data:`app` built lazily by :func:`run`.

    ``curations_dir`` and ``state_path`` override the on-disk locations
    used by the new Phase 1B curation CRUD endpoints; tests point them
    at ``tmp_path`` to keep the user's real ``~/stemforge`` untouched.

    ``processed_dir`` overrides the forge-scan root for the Phase 1.5
    ``/forges`` endpoints (defaults to ``~/stemforge/processed``).
    ``subprocess_runner`` is an injection seam for tests — defaults to
    :func:`subprocess.run`. Production code never overrides it; the test
    suite stubs it to avoid spawning real ``stemforge`` invocations.

    ``templates_dir`` overrides the templates-scan root for the Phase 3A
    ``/templates`` endpoint (defaults to ``~/stemforge/templates``).
    ``device_notifier`` is the Phase 3A server→device notify seam — a
    callable ``(route: str, *args: str) -> None`` that fires the
    notification at the strip device. Production uses a UDP datagram to
    ``localhost:7420`` (matches the device's existing ``[udpreceive]``
    port). Tests inject a list-appending stub for assertion.
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
    resolved_processed = (
        Path(processed_dir).expanduser().resolve()
        if processed_dir is not None
        else (
            Path(os.environ[PROCESSED_DIR_ENV]).expanduser().resolve()
            if os.environ.get(PROCESSED_DIR_ENV)
            else default_processed_dir()
        )
    )
    resolved_templates = (
        Path(templates_dir).expanduser().resolve()
        if templates_dir is not None
        else (
            Path(os.environ[TEMPLATES_DIR_ENV]).expanduser().resolve()
            if os.environ.get(TEMPLATES_DIR_ENV)
            else default_templates_dir()
        )
    )
    state.curations_dir = resolved_curations
    state.state_path = resolved_state_path
    # Phase 4A: prime the in-memory StemforgeState cache from disk so the
    # device-bootstrap path (``POST /als-opened``) doesn't pay an I/O hit
    # on every request. ``load_state_with_recovery`` handles a malformed
    # state file by archiving it and resetting to empty — the server
    # keeps booting either way.
    state.refresh_cached_stemforge_state()

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
    app.state.processed_dir = resolved_processed
    app.state.templates_dir = resolved_templates
    app.state.loaded_forges = set()
    app.state.subprocess_runner = subprocess_runner or subprocess.run
    app.state.device_notifier = device_notifier or _default_device_notifier()

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


def _default_device_notifier() -> Any:
    """Build the production server→device notifier (UDP datagram to localhost).

    The patcher exposes a ``[udpreceive 7420]`` object that routes incoming
    space-separated messages — first token is the route name, remaining
    tokens are the route args. Our wire shape is::

        <route> <arg1> <arg2> ...

    e.g. ``template-changed A drum-rack-classic``. The device's JS routes
    that off the patcher's [route template-changed ...] table into
    :func:`templateChanged` (mirror naming TBD in Phase 3A device JS).

    A new datagram is sent for every notification — there's no
    persistent connection. Failures (port closed, no listener) are
    logged and swallowed; the device might simply not be running yet.
    """
    port_env = os.environ.get(DEVICE_UDP_PORT_ENV)
    try:
        port = int(port_env) if port_env else DEFAULT_DEVICE_UDP_PORT
    except ValueError:
        port = DEFAULT_DEVICE_UDP_PORT

    def _notify(route: str, *args: str) -> None:
        # The patcher's existing [udpreceive 7420] runs in OSC mode (verified
        # 2026-05-09 against /tmp/udp_probe). Max emits the address as a
        # single symbol with leading-slash preserved, and downstream
        # `[route /state /forge ...]` matches the leading slash. So we
        # MUST prefix our route with `/` to land in the dispatcher.
        route_str = str(route)
        osc_addr = "/" + route_str if not route_str.startswith("/") else route_str
        msg_parts: list[str] = [osc_addr]
        for arg in args:
            msg_parts.append(str(arg))
        payload = " ".join(msg_parts).encode("utf-8")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(payload, (DEFAULT_DEVICE_UDP_HOST, port))
        except OSError:
            # No listener / network blip — the device may not be open.
            # Phase 4 may add a retry-or-acked variant; for now the
            # popup's SSE broadcast is the user-facing signal.
            return

    return _notify


# ── Phase 1.5 forge endpoint bodies ──────────────────────────────────────────


class ReAnchorBody(BaseModel):
    """Body of ``POST /forges/{slug}/re-anchor`` (Phase 1.5).

    Accepts both the spec's ``downbeat_sec`` and the task brief's
    ``first_downbeat_seconds`` for the same field. The CLI ultimately
    receives ``--first-downbeat <float>``. ``source_bpm`` (when non-null)
    maps to the CLI's ``--bpm`` flag; the CLI command requires both.
    """

    downbeat_sec: float | None = Field(default=None, ge=0.0)
    first_downbeat_seconds: float | None = Field(default=None, ge=0.0)
    source_bpm: float | None = Field(default=None, gt=0.0)

    model_config = {"extra": "forbid"}

    @property
    def downbeat(self) -> float:
        """Effective downbeat value (in seconds), preferring whichever was set."""
        if self.downbeat_sec is not None:
            return self.downbeat_sec
        if self.first_downbeat_seconds is not None:
            return self.first_downbeat_seconds
        raise ValueError("re-anchor requires downbeat_sec or first_downbeat_seconds")


class ReCurateBody(BaseModel):
    """Body of ``POST /forges/{slug}/re-curate`` (Phase 1.5).

    The underlying ``stemforge re-curate`` command takes no positional
    args beyond the slug; ``params`` is accepted for forward-compat with
    the popup's :class:`ReCurateRequest` but unused in v1.
    """

    params: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}


# ── Phase 3C — EXPORT bodies ────────────────────────────────────────────────


class ExportCurationBody(BaseModel):
    """Body of ``POST /curations/{name}/export`` (Phase 3C).

    Matches the popup-side :class:`ExportCurationRequest` shim shipped by
    Lane 1D. ``target_format`` defaults to ``"ppak"`` and is validated
    server-side against :data:`export_handler.KNOWN_TARGET_FORMATS`.
    """

    out_path: str = Field(..., min_length=1)
    target_format: str = Field(default=DEFAULT_TARGET_FORMAT)

    model_config = {"extra": "forbid"}


class PickSavePathBody(BaseModel):
    """Body of ``POST /intent/pick-save-path`` (Phase 3C).

    Optional ``default_name`` + ``default_dir`` seed the osascript
    "choose file name" dialog. Both are advisory — the OS may ignore
    them on minimal Apple installs.
    """

    default_name: str | None = Field(
        default=None,
        description="Suggested filename for the save dialog (e.g. 'my_kit.ppak').",
    )
    default_dir: str | None = Field(
        default=None,
        description=(
            "Suggested directory to open the dialog in. Defaults to the user's "
            "Desktop — matches the EP-133 .ppak output convention "
            "(memory feedback_ep133_ppak_output_path.md)."
        ),
    )
    prompt: str | None = Field(
        default=None,
        description="Optional title text for the macOS save dialog.",
    )

    model_config = {"extra": "forbid"}


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
        # Phase 3A: hand the templates_dir + notifier down so the handler can
        # validate the template exists AND notify the device to hot-apply.
        return await intents.handle_patch_template(
            state,
            name,
            body,
            templates_dir=app.state.templates_dir,
            device_notifier=app.state.device_notifier,
        )

    @app.patch("/curations/{name}/target", response_model=Curation)
    async def patch_target_route(name: str, body: PatchTargetBody) -> Curation:
        return await intents.handle_patch_target(state, name, body)

    @app.post("/curations/{name}/commit", response_model=Curation)
    async def commit_curation_route(name: str, body: DeviceCommitBody) -> Curation:
        # Pass app.state.processed_dir explicitly so the reverse-lookup
        # honours per-test ``processed_dir`` overrides (the integration
        # test points this at a tmp_path with fixture forges).
        return await intents.handle_curation_commit(
            state,
            name,
            body,
            processed_dir=app.state.processed_dir,
        )

    # ── BOUNCE (Phase 3B, spec §4.3 + §5.5) ───────────────────────────────

    @app.post("/curations/{name}/trigger-bounce")
    async def trigger_bounce_route(name: str, body: TriggerBounceBody) -> dict[str, Any]:
        # Async kickoff: validates curation + spec, broadcasts the spec via
        # SSE for the device's listener to pick up, returns the spec to the
        # popup so the user sees what's about to render. The actual WAV
        # rendering happens device-side; completion arrives via
        # /bounce-progress + /bounce-complete below.
        return await intents.handle_trigger_bounce(state, name, body)

    @app.post("/curations/{name}/bounce-progress")
    async def bounce_progress_route(name: str, body: BounceProgress) -> dict[str, Any]:
        return await intents.handle_bounce_progress(state, name, body)

    @app.post("/curations/{name}/bounce-complete", response_model=Curation)
    async def bounce_complete_route(name: str, body: BounceCompletion) -> Curation:
        return await intents.handle_bounce_complete(state, name, body)

    # ── Phase 1.5 — curation rename / active close ─────────────────────────

    @app.post("/curations/{name}/rename", response_model=Curation)
    async def rename_curation_route(name: str, body: RenameCurationBody) -> Curation:
        return await intents.handle_rename_curation(state, name, body)

    @app.post("/curations/active/close")
    async def close_active_curation_route(body: CloseActiveCurationBody) -> dict[str, Any]:
        return await intents.handle_close_active_curation(state, body)

    # ── Phase 4A — device bootstrap on Live `.als` open ────────────────────

    @app.post("/als-opened")
    async def als_opened_route(body: AlsOpenedBody) -> dict[str, Any]:
        """Device-driven bootstrap: resolve the active curation for ``als_path``.

        See :func:`intents.handle_als_opened`. The response body carries
        ``active_curation: str | null`` — the device's HTTP shim hands it
        back to the loader JS via ``messnamed("sf-als-opened-ack", name)``.
        """
        return await intents.handle_als_opened(state, body)

    # ── Phase 3A — template index ──────────────────────────────────────────

    @app.get("/templates")
    async def list_templates_route() -> dict[str, Any]:
        """Return the ``.adg`` templates under ``~/stemforge/templates/``.

        Stable alphabetical sort. Empty dir → ``{"templates": []}``. The
        popup's ActiveCuration panel calls this on mount to populate the
        per-group template dropdown.
        """
        entries = list_templates(app.state.templates_dir)
        return {"templates": [e.to_dict() for e in entries]}

    # ── Phase 1.5 — forge endpoints ────────────────────────────────────────

    @app.get("/forges")
    async def list_forges_route() -> dict[str, Any]:
        entries = list_forges(app.state.processed_dir)
        return {"forges": [e.to_dict() for e in entries]}

    @app.post("/forges/{slug}/load")
    async def load_forge_route(slug: str) -> dict[str, Any]:
        forge_dir = resolve_forge_dir(app.state.processed_dir, slug)
        async with state.mutation_lock:
            app.state.loaded_forges.add(slug)
        await state.log(f"loaded forge {slug}", "info")
        await _broadcast_forge_state(state, app.state.loaded_forges)
        return {"ok": True, "slug": slug, "path": str(forge_dir)}

    @app.post("/forges/{slug}/unload")
    async def unload_forge_route(slug: str) -> dict[str, Any]:
        # Slug validity check; unload of an unknown slug is still a 404
        # so the popup can surface "nothing to unload" cleanly.
        resolve_forge_dir(app.state.processed_dir, slug)
        async with state.mutation_lock:
            app.state.loaded_forges.discard(slug)
        await state.log(f"unloaded forge {slug}", "info")
        await _broadcast_forge_state(state, app.state.loaded_forges)
        return {"ok": True, "slug": slug}

    @app.post("/forges/{slug}/reveal")
    async def reveal_forge_route(slug: str) -> dict[str, Any]:
        forge_dir = resolve_forge_dir(app.state.processed_dir, slug)
        runner = app.state.subprocess_runner
        try:
            runner(["open", str(forge_dir)], check=False)
        except FileNotFoundError as exc:
            # ``open`` is missing — likely a non-macOS CI runner. Surface
            # the failure plainly rather than masking with a 500.
            raise HTTPException(
                status_code=500,
                detail=f"unable to invoke 'open': {exc}",
            ) from exc
        return {"ok": True, "path": str(forge_dir)}

    @app.post("/forges/{slug}/re-anchor")
    async def re_anchor_forge_route(slug: str, body: ReAnchorBody) -> dict[str, Any]:
        forge_dir = resolve_forge_dir(app.state.processed_dir, slug)
        try:
            downbeat = body.downbeat
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if body.source_bpm is None:
            # ``stemforge re-anchor`` requires --bpm. Bubble that
            # constraint up as a 422 so the popup can prompt for it.
            raise HTTPException(
                status_code=422,
                detail="re-anchor requires source_bpm (the CLI's --bpm flag)",
            )
        cmd = [
            "uv",
            "run",
            "stemforge",
            "re-anchor",
            str(forge_dir),
            "--bpm",
            str(body.source_bpm),
            "--first-downbeat",
            str(downbeat),
        ]
        runner = app.state.subprocess_runner
        proc = runner(cmd, capture_output=True, text=True, check=False)
        ok = getattr(proc, "returncode", 1) == 0
        stdout = getattr(proc, "stdout", "") or ""
        stderr = getattr(proc, "stderr", "") or ""
        if ok:
            await state.log(f"re-anchored forge {slug}", "info")
            await _broadcast_forge_state(state, app.state.loaded_forges)
        else:
            await state.error("re_anchor_failed", stderr.strip() or "re-anchor failed")
        return {"ok": ok, "slug": slug, "stdout": stdout, "stderr": stderr}

    # ── Phase 3C — EXPORT ──────────────────────────────────────────────────

    @app.post("/curations/{name}/export")
    async def export_curation_route(
        name: str,
        body: ExportCurationBody,
    ) -> dict[str, Any]:
        """Export the named curation to a hardware target's bundle format.

        Shells out to ``uv run stemforge export <name> --target <fmt>
        --out <path>``. On success, updates ``curation.last_export`` and
        broadcasts a state SSE event. On subprocess failure, returns 200
        with ``{ok: false, stderr, stdout}`` so the popup popup can
        render the diagnostics inline (mirrors the re-anchor pattern).

        4xx codes are reserved for input validation failures:

        * 400 — invalid name, traversal in out_path, unknown target_format,
          missing parent dir.
        * 404 — curation not found on disk.
        """
        runner = app.state.subprocess_runner
        async with state.mutation_lock:
            try:
                result = perform_export(
                    curations_dir=state.curations_dir,
                    name=name,
                    out_path_raw=body.out_path,
                    target_format_raw=body.target_format,
                    subprocess_runner=runner,
                )
            except ExportValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

        if result.ok:
            await state.log(
                f"exported curation {name} → {body.out_path}",
                "info",
            )
            await state.broadcast_curations_state()
        else:
            await state.error(
                "export_failed",
                (result.stderr.strip() or result.error or "export failed"),
            )

        body_out = result.to_dict()
        body_out["name"] = name
        return body_out

    @app.post("/intent/pick-save-path")
    async def pick_save_path_route(body: PickSavePathBody) -> dict[str, Any]:
        """Server-side osascript "save as" dialog → returns ``{path: str|null}``.

        Lives server-side because the popup runs inside Live's [jweb]
        host without filesystem access. Mirrors the v0.2 ``pick-manifest``
        helper but defaults the dialog at ``~/Desktop`` to match the
        EP-133 .ppak output convention.
        """
        runner = app.state.subprocess_runner
        chosen = _osascript_pick_save_path(
            runner=runner,
            default_name=body.default_name,
            default_dir=body.default_dir,
            prompt=body.prompt,
        )
        return {"ok": True, "path": chosen}

    @app.post("/forges/{slug}/re-curate")
    async def re_curate_forge_route(slug: str, body: ReCurateBody) -> dict[str, Any]:
        # ``params`` is currently advisory only; the CLI subcommand takes
        # no extra positional args beyond the slug.
        _ = body
        resolve_forge_dir(app.state.processed_dir, slug)
        cmd = ["uv", "run", "stemforge", "re-curate", slug]
        runner = app.state.subprocess_runner
        proc = runner(cmd, capture_output=True, text=True, check=False)
        ok = getattr(proc, "returncode", 1) == 0
        stdout = getattr(proc, "stdout", "") or ""
        stderr = getattr(proc, "stderr", "") or ""
        if ok:
            await state.log(f"re-curated forge {slug}", "info")
            await _broadcast_forge_state(state, app.state.loaded_forges)
        else:
            await state.error("re_curate_failed", stderr.strip() or "re-curate failed")
        return {"ok": ok, "slug": slug, "stdout": stdout, "stderr": stderr}


def _osascript_pick_save_path(
    *,
    runner: Any,
    default_name: str | None = None,
    default_dir: str | None = None,
    prompt: str | None = None,
) -> str | None:
    """Drive an ``osascript`` "choose file name" dialog → POSIX path or None.

    Uses the standard AppleScript ``choose file name`` verb so we get a
    real save-as dialog (vs. ``choose file`` which is open-only). The
    result POSIX path is captured from stdout. User-cancel surfaces as
    an empty string / non-zero exit ⇒ we return ``None``.

    The subprocess invocation flows through ``runner`` (defaults to
    :func:`subprocess.run`) so tests stub it cleanly.
    """
    default_name = (default_name or "untitled.ppak").strip()
    default_dir_path = Path(default_dir).expanduser() if default_dir else (Path.home() / "Desktop")
    prompt_text = prompt or "Save export bundle"

    # AppleScript: choose file name returns the chosen file alias; we
    # coerce to POSIX path text and print it on stdout. ``default location``
    # accepts an alias; we build one via ``POSIX file``. If the user
    # cancels, the script errors (-128); we treat any non-zero exit as
    # "no selection".
    script = (
        "set theFile to (choose file name "
        f'with prompt "{_applescript_escape(prompt_text)}" '
        f'default name "{_applescript_escape(default_name)}" '
        f'default location (POSIX file "{_applescript_escape(str(default_dir_path))}"))\n'
        "POSIX path of theFile"
    )
    cmd = ["osascript", "-e", script]
    try:
        proc = runner(cmd, capture_output=True, text=True, timeout=120, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    chosen = (getattr(proc, "stdout", "") or "").strip()
    return chosen or None


def _applescript_escape(value: str) -> str:
    """Quote-escape a string for inline embedding in AppleScript source."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def _broadcast_forge_state(state: AppState, loaded: set[str]) -> None:
    """Push a ``state`` SSE event carrying the loaded-forge set.

    Distinct ``kind`` field so the popup can dispatch on it. We surface
    ``loaded_forge`` (singular) as the last-loaded slug — matches the
    task brief's wire shape — and ``loaded_forges`` (plural) as the full
    set so future multi-load UIs keep working.
    """
    import time as _time

    last = sorted(loaded)[-1] if loaded else None
    await state.broadcast(
        SseEvent(
            event="state",
            data={
                "kind": "forges",
                "loaded_forge": last,
                "loaded_forges": sorted(loaded),
                "ts": _time.time(),
            },
        )
    )


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
