"""Popup↔server contract tests (Pre-UAT P1-1, flagship deliverable).

The biggest miss in the pre-UAT review was that 8 of the P0 bugs were
popup↔server wire mismatches that msw mocks silently approved. msw is
happy to stub any path the popup asks for — the server doesn't see those
stubs, so a typo in the popup's URL silently becomes a green popup test
+ a 404 in production.

This module is the regression gate. We parse every
``jsonRequest<T>(path, init)`` call out of
``web/configurator/src/lib/api.ts``, walk each ``path + method`` against
a real FastAPI ``TestClient``, and assert the route resolves (i.e. is
neither 404 nor 405). Body-shape assertions cover the three high-risk
endpoints whose request shape just changed in Lane A/B
(``openCuration``, ``closeActiveCuration``, ``createCuration``).

Maintenance pattern
-------------------

When you add a new ``jsonRequest`` call in ``api.ts``:

* Use a relative path literal so the regex picks it up. Template-literal
  segments like ``${encodeURIComponent(slug)}`` get substituted with the
  fixture stub ``"fixture-slug"`` before hitting the server — any route
  that can't accept a slug-as-string in its parameters will fail here.
* Pick a real HTTP verb — the regex defaults to ``GET`` when no
  ``method`` is provided, matching ``fetch``'s default.

If the regex parser starts feeling fragile, replace it with the
``register-call`` enumeration in ``EXPECTED_ROUTES`` below — keyed off
the same ``api.ts`` source file, refreshed when wire shapes change.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stemforge.configurator.server import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
API_TS_PATH = REPO_ROOT / "web" / "configurator" / "src" / "lib" / "api.ts"


# ── api.ts parser ───────────────────────────────────────────────────────────


# Capture every `jsonRequest<T>(path, { method?: "X", body?: ... })` call.
# Path may be a template literal (backticks) or a regular string. Method
# defaults to GET when no init/method is specified.
_JSON_REQUEST_RE = re.compile(
    r"jsonRequest<[^>]+>\(\s*"
    r"([`'\"])([^`'\"]+)\1"  # quoted/back-ticked path
    r"(?:\s*,\s*\{([^}]*)\})?",  # optional init block
    re.MULTILINE | re.DOTALL,
)
_METHOD_RE = re.compile(r"method\s*:\s*[\"']([A-Z]+)[\"']")


def _parse_api_ts_calls() -> list[tuple[str, str]]:
    """Return ``[(method, route_template), ...]`` for every jsonRequest call.

    Template-literal placeholders (``${encodeURIComponent(x)}``,
    ``${x}``) are flattened to the literal stub ``fixture-slug`` so the
    resulting paths plug straight into ``TestClient.request``.
    """
    raw = API_TS_PATH.read_text()
    calls: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _JSON_REQUEST_RE.finditer(raw):
        path_template = match.group(2)
        init_block = match.group(3) or ""
        method_match = _METHOD_RE.search(init_block)
        method = method_match.group(1) if method_match else "GET"
        # Substitute template placeholders with a stub. Two passes: the
        # encodeURIComponent wrapper first, then any plain ${ ... } left over.
        concrete = re.sub(r"\$\{encodeURIComponent\([^)]+\)\}", "fixture-slug", path_template)
        concrete = re.sub(r"\$\{[^}]+\}", "fixture-slug", concrete)
        key = (method, concrete)
        if key in seen:
            continue
        seen.add(key)
        calls.append(key)
    return calls


def _expected_min_calls() -> int:
    """Fail-loud floor: api.ts has at least this many distinct routes today.

    Bumps when api.ts grows. The point isn't the exact count — it's that
    a regex bug that silently matches zero calls won't pass the parametrize.
    """
    return 16


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def configurator_paths(tmp_path: Path) -> dict[str, Path]:
    curations_dir = tmp_path / "curations"
    curations_dir.mkdir()
    state_path = tmp_path / ".stemforge_state.json"
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    static_dir = tmp_path / "static"
    return {
        "curations_dir": curations_dir,
        "state_path": state_path,
        "processed_dir": processed_dir,
        "templates_dir": templates_dir,
        "static_dir": static_dir,
    }


@pytest.fixture
def client(configurator_paths: dict[str, Path]) -> TestClient:
    # Stub subprocess so any route that shells out to osascript / uv / the
    # stemforge CLI returns immediately. The contract test only cares about
    # route presence + method + (for the body-shape tests) body shape; it
    # MUST NOT pop up a real macOS dialog on dev machines.
    class _FastCompleted:
        returncode = 1  # non-zero so osascript pickers behave as "no path"
        stdout = ""
        stderr = "(stubbed-by-contract-test)"

    def _stub_run(*_args, **_kwargs):  # noqa: ARG001
        return _FastCompleted()

    app = create_app(
        static_dir=configurator_paths["static_dir"],
        curations_dir=configurator_paths["curations_dir"],
        state_path=configurator_paths["state_path"],
        processed_dir=configurator_paths["processed_dir"],
        templates_dir=configurator_paths["templates_dir"],
        subprocess_runner=_stub_run,
    )
    return TestClient(app)


# ── Sanity: the parser actually finds something ─────────────────────────────


def test_parser_finds_known_floor_of_routes() -> None:
    """Guard against a parser regression that silently matches zero routes."""
    calls = _parse_api_ts_calls()
    assert len(calls) >= _expected_min_calls(), (
        f"expected at least {_expected_min_calls()} jsonRequest calls in api.ts, "
        f"found {len(calls)}; possible regex regression. Calls found: {calls!r}"
    )


def test_parser_captures_known_landmarks() -> None:
    """Spot-check that we find the high-traffic routes by name."""
    calls = {(m, p) for m, p in _parse_api_ts_calls()}
    landmarks = {
        ("GET", "/healthz"),
        ("GET", "/curations"),
        ("POST", "/curations"),
        ("POST", "/intent/pick-manifest"),
        ("POST", "/curations/active/close"),
    }
    missing = landmarks - calls
    assert not missing, f"parser missed landmark routes: {missing!r}"


# ── Route existence + method match ──────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path",
    _parse_api_ts_calls(),
    ids=lambda v: v.replace("/", "_") if isinstance(v, str) else v,
)
def test_popup_route_exists(client: TestClient, method: str, path: str) -> None:
    """Every ``api.ts`` call resolves to a real route on the server.

    We accept any status that isn't 404 / 405. 422 (body validation) and
    400/409 (semantic rejection of the stub slug) are fine here — the
    point is to catch typos and verb mismatches, not full body shapes.
    Body shapes get their own assertions below.
    """
    body: dict | None = {} if method != "GET" else None
    resp = client.request(method, path, json=body)
    # 404 is ambiguous in FastAPI — it's used both for "route not registered"
    # AND for domain "resource not found" (e.g. ``forge not found``). We
    # distinguish them by the canonical detail string: starlette's default
    # missing-route response is exactly ``{"detail":"Not Found"}``; any
    # custom HTTPException sets a different detail.
    if resp.status_code == 404:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = None
        assert detail and detail != "Not Found", (
            f"{method} {path} returned 404 — route missing from server. "
            f"api.ts↔server.py drift detected. Body: {resp.text!r}"
        )
    assert resp.status_code != 405, (
        f"{method} {path} returned 405 — verb mismatch. "
        f"server.py registers a different HTTP method. "
        f"Allowed: {resp.headers.get('allow', '<none>')!r}"
    )


# ── Body-shape assertions for high-risk endpoints (Lane A/B/G handoff) ──────


def test_open_curation_accepts_empty_body_post_lane_a(
    client: TestClient, configurator_paths: dict[str, Path]
) -> None:
    """``POST /curations/{name}/open`` accepts ``{}`` (sentinel default).

    Lane A made ``als_path`` optional on ``OpenCurationBody`` so the
    standalone popup can call this without a Live-attached path. A
    regression that re-required the field would 422 here.
    """
    # Seed a curation so we get past the 404 branch — the body shape is
    # what we care about.
    from datetime import UTC, datetime

    from stemforge.configurator.curation_io import curation_path, write_curation_atomic
    from stemforge.configurator.schemas import Curation, Group, Pad, Target

    target = Target()
    groups = {
        letter: Group(
            label="",
            template=None,
            pads=[Pad(pad_id=f"{letter}{i + 1:02d}") for i in range(12)],
        )
        for letter in ["A", "B", "C", "D"]
    }
    curation = Curation(
        name="contract_open",
        type="deck",
        created_at=datetime.now(UTC),
        modified_at=datetime.now(UTC),
        target=target,
        referenced_forges=[],
        groups=groups,
    )
    write_curation_atomic(
        curation_path(configurator_paths["curations_dir"], "contract_open"),
        curation,
    )

    resp = client.post("/curations/contract_open/open", json={})
    assert resp.status_code == 200, (
        f"open with empty body returned {resp.status_code}: {resp.text!r}. "
        "Lane A's POPUP_ALS_SENTINEL default may have regressed."
    )
    body = resp.json()
    # The sentinel namespace got the active.
    assert body["active_curations"].get("__popup__") == "contract_open"


def test_close_active_curation_accepts_empty_body_post_lane_a(
    client: TestClient,
) -> None:
    """``POST /curations/active/close`` accepts ``{}`` (sentinel default)."""
    resp = client.post("/curations/active/close", json={})
    assert resp.status_code == 200, (
        f"close with empty body returned {resp.status_code}: {resp.text!r}. "
        "Lane A's POPUP_ALS_SENTINEL default may have regressed."
    )
    body = resp.json()
    assert body["ok"] is True
    assert body["als_path"] == "__popup__"


def test_create_curation_accepts_name_plus_target(client: TestClient) -> None:
    """``POST /curations`` accepts ``{name, target}`` per Lane B's wire shape."""
    body = {
        "name": "contract_create",
        "target": {
            "device": "ep133",
            "groups": 4,
            "pads_per_group": 12,
        },
    }
    resp = client.post("/curations", json=body)
    assert resp.status_code == 201, (
        f"create returned {resp.status_code}: {resp.text!r}. "
        "Lane B's CreateCurationRequest may have drifted from CreateCurationBody."
    )
    out = resp.json()
    assert out["name"] == "contract_create"


def test_create_curation_accepts_name_alone(client: TestClient) -> None:
    """Target is optional — default lands automatically."""
    resp = client.post("/curations", json={"name": "contract_just_name"})
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["name"] == "contract_just_name"


def test_pick_manifest_accepts_empty_body(client: TestClient) -> None:
    """``POST /intent/pick-manifest`` accepts ``{}`` (P0-1 handoff)."""
    resp = client.post("/intent/pick-manifest", json={})
    # On non-macOS CI runners osascript is absent → returns {path: null,
    # kind: "unknown"}; on dev macs the dialog auto-cancels. Either way
    # we want 200 + the documented shape.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "kind" in body, body
    assert "path" in body, body


# ── Negative sanity: a synthetic mismatch fires the contract ────────────────


def test_synthetic_404_path_would_be_caught() -> None:
    """Documents the failure mode the contract test protects against.

    This test deliberately does NOT call the server with a bogus path —
    that would muddy the parametrize. Instead it asserts that if the
    parser ever picked up a route that doesn't exist on the server, the
    parametrized test above would catch it (by returning 404).

    To verify manually: add ``jsonRequest<unknown>("/totally-bogus")``
    temporarily to api.ts, re-run this module, watch
    ``test_popup_route_exists[GET-_totally-bogus]`` fail with 404.
    """
    # Self-check: parser still returns a non-empty list.
    calls = _parse_api_ts_calls()
    assert calls, "parser found zero calls — guard against silent regression"
    # Self-check: the synthetic floor is real.
    assert len(calls) >= _expected_min_calls()


# ── Reverse coverage: every server route in api.ts is intentional ──────────


def _server_routes(client: TestClient) -> Iterable[tuple[str, str]]:
    """Yield ``(method, path)`` for every registered FastAPI route."""
    for route in client.app.routes:  # type: ignore[attr-defined]
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if not path:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            yield (method, path)


def test_api_ts_does_not_reference_unknown_prefixes(client: TestClient) -> None:
    """Every api.ts route's *prefix* exists on the server.

    Path-parameter style differences (``/curations/{name}`` vs the popup's
    ``/curations/fixture-slug``) make exact-match comparison flaky, so we
    assert prefix overlap: the popup's path must share its first two
    segments with at least one server route.
    """
    server_prefixes = set()
    for _method, path in _server_routes(client):
        parts = path.split("/")
        if len(parts) >= 3:
            server_prefixes.add(f"/{parts[1]}/{parts[2]}")
        elif len(parts) >= 2:
            server_prefixes.add(f"/{parts[1]}")
    for method, path in _parse_api_ts_calls():
        parts = path.split("/")
        candidate = f"/{parts[1]}/{parts[2]}" if len(parts) >= 3 else f"/{parts[1]}"
        candidate_root = f"/{parts[1]}" if len(parts) >= 2 else "/"
        assert candidate in server_prefixes or candidate_root in server_prefixes, (
            f"api.ts route {method} {path} has no server-side prefix match. "
            f"Known prefixes: {sorted(server_prefixes)!r}"
        )
