"""osascript wrappers for driving Ableton Live from the smoke runner.

These functions are *thin* — they build a command string and shell out
to ``osascript -e ...``. Tests verify the command-string construction
(via ``monkeypatch`` against ``_run`` / ``subprocess.run``); the actual
AppleScript dispatch happens on a real Mac with Live installed.

Why osascript and not Live's OSC remote-script: we want zero-touch on
the user's Live install — no remote scripts, no MIDI remote, no extra
plugins. ``osascript -e 'tell application "X" to open POSIX file "..."'``
works against a stock Live install.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

# Common install locations, in resolution order. The runner picks the
# first match — Beta wins over Suite if both are present (developer
# preference; override with ``--live-app``).
CANDIDATE_APPS: tuple[str, ...] = (
    "/Applications/Ableton Live 12 Beta.app",
    "/Applications/Ableton Live 12 Suite.app",
    "/Applications/Ableton Live 12 Standard.app",
    "/Applications/Ableton Live 11 Suite.app",
    "/Applications/Ableton Live 11 Standard.app",
)


def find_live_app(candidates: tuple[str, ...] = CANDIDATE_APPS) -> Path | None:
    """Return the first existing Live ``.app`` bundle, or ``None``."""
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p
    return None


def app_display_name(app_path: Path) -> str:
    """Strip ``.app`` from the bundle name so AppleScript can ``tell`` it.

    e.g. ``/Applications/Ableton Live 12 Suite.app`` →
    ``Ableton Live 12 Suite``. AppleScript's ``tell application "..."``
    wants the display name, not the file path.
    """
    return app_path.stem


def build_open_als_command(app_path: Path, als_path: Path) -> list[str]:
    """Build the ``osascript`` argv that opens the given ``.als`` in Live.

    Pure: returns argv; does not run. Tested.
    """
    name = app_display_name(app_path)
    posix = str(als_path)
    script = f'tell application "{name}"\n    activate\n    open POSIX file "{posix}"\nend tell'
    return ["osascript", "-e", script]


def build_quit_command(app_path: Path) -> list[str]:
    """Build the ``osascript`` argv that quits Live (no save prompt)."""
    name = app_display_name(app_path)
    script = f'tell application "{name}"\n    quit saving no\nend tell'
    return ["osascript", "-e", script]


def _run(argv: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Wrapped subprocess.run so tests can monkeypatch this one symbol."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def open_als(app_path: Path, als_path: Path, *, timeout: float = 30.0) -> bool:
    """Tell Live to open the given ``.als``. Returns True on rc=0."""
    if not als_path.exists():
        raise FileNotFoundError(f"als fixture missing: {als_path}")
    argv = build_open_als_command(app_path, als_path)
    cp = _run(argv, timeout=timeout)
    return cp.returncode == 0


def quit_live(app_path: Path, *, timeout: float = 15.0) -> bool:
    """Tell Live to quit. Returns True on rc=0."""
    argv = build_quit_command(app_path)
    cp = _run(argv, timeout=timeout)
    return cp.returncode == 0


def render_command_string(argv: list[str]) -> str:
    """For diagnostics / `--list` output. Shell-quotes the argv."""
    return " ".join(shlex.quote(a) for a in argv)
