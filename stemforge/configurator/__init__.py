"""Configurator HTTP server (Phase 3, Lane A).

Local-only FastAPI app that holds the canonical :class:`Project` spec in
memory and exposes:

- ``GET /state`` — current :class:`Project` JSON.
- ``GET /state/stream`` — Server-Sent Events stream (``state``, ``log``,
  ``progress``, ``error``).
- ``GET /preview/<clip_id>`` — Range-aware WAV streaming for clip preview.
- ``GET /healthz`` — liveness check used by the strip device.
- ``POST /intent/*`` — single-writer mutation endpoints: ``load-manifest``,
  ``commit``, ``assign-pad``, ``clear-pad``, ``set-group-format``,
  ``recompute``, ``export``.

The server is the **single writer** to the slot table (configurator spec
v4 Decision 15). Every other surface — strip device, popup, COMMIT —
sends intents and receives state via SSE.

Entry points:

- :func:`stemforge.configurator.server.run` (also exposed as the
  ``stemforge-configurator`` console script).
- :mod:`tools.m4l_configurator_server` (thin wrapper used by the
  M4L ``[shell]`` launcher).
"""

from __future__ import annotations

__all__: list[str] = []
