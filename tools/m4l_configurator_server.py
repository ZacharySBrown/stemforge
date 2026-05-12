"""Thin entry point for the configurator HTTP server.

Wraps :func:`stemforge.configurator.server.run` so the M4L ``[shell]``
launcher can invoke ``uv run python tools/m4l_configurator_server.py``
without depending on the console-script install hook.

Same module also pairs with the ``stemforge-configurator`` console
script declared in ``pyproject.toml`` — both end up calling ``run()``.
"""

from __future__ import annotations

from stemforge.configurator.server import run

if __name__ == "__main__":
    run()
