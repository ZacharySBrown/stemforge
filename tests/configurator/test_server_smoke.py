"""End-to-end smoke test for the configurator HTTP server.

Spawns uvicorn in a subprocess (similar to ``tests/test_canonical_tempos.py``'s
``_run_split`` pattern), waits for ``/healthz`` to respond, and exercises the
core surfaces (state, healthz, 422 on bad input). The subprocess pattern keeps
asyncio loops + uvicorn state out of the test runner's process.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(port: int, *, timeout_sec: float = 15.0) -> None:
    deadline = time.time() + timeout_sec
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1.0)
            if r.status_code == 200:
                return
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_err = exc
        time.sleep(0.2)
    raise AssertionError(f"server never came up on :{port}: {last_err!r}")


@pytest.fixture
def running_server(tmp_path: Path):
    port = _free_port()
    env = {
        **os.environ,
        "STEMFORGE_CONFIGURATOR_PORT": str(port),
        "STEMFORGE_CONFIGURATOR_STATIC": str(tmp_path / "static"),
    }
    # Invoke the console-entry helper via -c so we don't need a __main__
    # guard on the module. ``run()`` reads STEMFORGE_CONFIGURATOR_PORT
    # from env, writes the port file, and boots uvicorn.
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from stemforge.configurator.server import run; run()",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_health(port)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_healthz_responds(running_server: int):
    r = httpx.get(f"http://127.0.0.1:{running_server}/healthz", timeout=2.0)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body


def test_state_returns_empty_project(running_server: int):
    r = httpx.get(f"http://127.0.0.1:{running_server}/state", timeout=2.0)
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == 2
    assert body["songs"] == []


def test_invalid_intent_returns_422(running_server: int):
    r = httpx.post(
        f"http://127.0.0.1:{running_server}/intent/assign-pad",
        json={"group": "Z", "pad": 99},  # both invalid
        timeout=2.0,
    )
    assert r.status_code == 422


def test_static_placeholder_served(running_server: int):
    r = httpx.get(f"http://127.0.0.1:{running_server}/", timeout=2.0)
    assert r.status_code == 200
    assert "Configurator" in r.text
