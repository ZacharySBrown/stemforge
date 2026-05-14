"""Thin wrapper around ``tools/sf_remote.py`` for the smoke runner.

We don't import sf_remote as a module because it's a CLI script; we
shell out. This keeps the smoke runner agnostic about sf_remote's
internal layout — if sf_remote grows new commands, we just pass them
through.

Also exposes ``healthz_ok()``, which is the heartbeat the runner uses
to know the device's ``[udpreceive]`` has come up after Live opens
a fixture ``.als``.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

REPO_ROOT = Path(__file__).resolve().parents[3]
SF_REMOTE = REPO_ROOT / "tools" / "sf_remote.py"


@dataclass
class CommandResult:
    rc: int
    stdout: str
    stderr: str


def _run(argv: list[str], *, timeout: float = 10.0) -> CommandResult:
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    return CommandResult(rc=cp.returncode, stdout=cp.stdout, stderr=cp.stderr)


def fire(target: str, *args: str, timeout: float = 5.0) -> CommandResult:
    """``sf-remote fire <target> <args...>`` — UDP bus message."""
    argv = [sys.executable, str(SF_REMOTE), "fire", target, *args]
    return _run(argv, timeout=timeout)


def dump(dictname: str, *, timeout: float = 5.0) -> CommandResult:
    """``sf-remote dump <dictname>`` — read a device dict via UDP+log."""
    argv = [sys.executable, str(SF_REMOTE), "dump", dictname, "--timeout", str(timeout)]
    return _run(argv, timeout=timeout + 2.0)


def healthz_ok(port: int, *, timeout: float = 2.0) -> bool:
    """GET ``/healthz`` on the configurator server. True on HTTP 200."""
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urlrequest.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (loopback only)
            return resp.status == 200
    except (urlerror.URLError, urlerror.HTTPError, TimeoutError, ConnectionError, OSError):
        return False


def read_port_file(port_file: Path) -> int | None:
    """Read the configurator port from ``~/stemforge/.configurator_port``."""
    if not port_file.exists():
        return None
    text = port_file.read_text().strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        # Some past versions wrote JSON. Be tolerant.
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and "port" in data:
            return int(data["port"])
        return None


def get_state(port: int, *, timeout: float = 5.0) -> dict | None:
    """GET ``/state`` on the configurator server. Returns parsed JSON or None."""
    url = f"http://127.0.0.1:{port}/state"
    try:
        with urlrequest.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (loopback only)
            return json.loads(resp.read().decode("utf-8"))
    except (
        urlerror.URLError,
        urlerror.HTTPError,
        TimeoutError,
        ConnectionError,
        OSError,
        json.JSONDecodeError,
    ):
        return None


def udp_port_open(port: int) -> bool:
    """Best-effort check that a UDP port is bound (sf_remote's bus = 7420).

    UDP is connectionless, so we can't truly "ping" it. We instead try
    to bind to the port — if we succeed, the port is FREE (and the
    device's ``[udpreceive]`` is NOT bound). Returns ``True`` if the
    port appears to be in use by another process (i.e. the device is
    listening).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", port))
        # We bound it — so the device wasn't listening.
        return False
    except OSError:
        # Couldn't bind — port is taken. Likely the device.
        return True
    finally:
        sock.close()
