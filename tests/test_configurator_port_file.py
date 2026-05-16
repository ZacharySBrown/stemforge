"""Port-file self-heal middleware tests.

The M4L strip device discovers the configurator by reading the port from
``~/stemforge/.configurator_port``. ``run()`` writes that file at launch,
but uvicorn ``--factory`` / import-string launches bypass ``run()`` and
leave a stale file pointing at a dead port. ``create_app`` installs a
first-request middleware that rewrites the file with the port the server
actually bound — these tests pin that behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stemforge.configurator.server import create_app


@pytest.fixture
def port_file(tmp_path: Path) -> Path:
    return tmp_path / ".configurator_port"


def _make_client(tmp_path: Path, port_file: Path, port: int) -> TestClient:
    app = create_app(
        static_dir=tmp_path / "static",
        curations_dir=tmp_path / "curations",
        state_path=tmp_path / ".stemforge_state.json",
        templates_dir=tmp_path / "templates",
        port_file=port_file,
    )
    # TestClient drops the port from request.url unless the base URL carries
    # one explicitly — the middleware reads request.url.port.
    return TestClient(app, base_url=f"http://testserver:{port}")


def test_first_request_writes_port_file(tmp_path: Path, port_file: Path) -> None:
    assert not port_file.exists()
    client = _make_client(tmp_path, port_file, 7438)
    client.get("/healthz")
    assert port_file.read_text() == "7438"


def test_stale_port_file_is_overwritten(tmp_path: Path, port_file: Path) -> None:
    port_file.write_text("59470")  # leftover from a dead prior server
    client = _make_client(tmp_path, port_file, 7431)
    client.get("/healthz")
    assert port_file.read_text() == "7431"


def test_port_file_written_once(tmp_path: Path, port_file: Path) -> None:
    """The write is one-shot — a later request must not re-touch the file."""
    client = _make_client(tmp_path, port_file, 7440)
    client.get("/healthz")
    first_mtime = port_file.stat().st_mtime_ns
    # A second request hits the guarded fast path — no write.
    client.get("/healthz")
    assert port_file.stat().st_mtime_ns == first_mtime
