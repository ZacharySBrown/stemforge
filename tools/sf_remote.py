"""sf_remote — headless remote debug CLI for the StemForge M4L device.

Drives the device running inside Max/Ableton on this Mac via UDP, and reads
its log via file tail. Lets you debug from a phone/other machine over SSH
while Live keeps running.

Usage examples:

    # Tail the device log (Ctrl-C to quit)
    uv run sf-remote log --follow

    # Fire a state transition through the UDP bus (port 7420)
    uv run sf-remote fire state markPhase1Progress 0.5 downloading vocals

    # Trigger the orchestrator
    uv run sf-remote fire forge startForge

    # Rescan presets / manifests
    uv run sf-remote fire preset-loader scan
    uv run sf-remote fire manifest-loader scanManifests

    # Dump a dict into the log (port 7421 → sf_state.dumpDict)
    uv run sf-remote dump sf_preset
    uv run sf-remote dump sf_manifest

    # Push canned state JSON into the UI
    uv run sf-remote setstate idle          # preset canned state
    uv run sf-remote setstate forging
    uv run sf-remote setstate /path/to/state.json

    # Clear the log (local + UDP to sf_logger clear)
    uv run sf-remote log clear

    # One-shot status dump: last 60 log lines + current sf_state + version
    uv run sf-remote status

The underlying protocol is documented in docs/remote_debug.md.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

UDP_HOST = os.environ.get("SF_REMOTE_HOST", "127.0.0.1")
UDP_BUS_PORT = int(os.environ.get("SF_REMOTE_BUS_PORT", "7420"))
UDP_DUMP_PORT = int(os.environ.get("SF_REMOTE_DUMP_PORT", "7421"))

LOG_PATH = Path.home() / "stemforge" / "logs" / "sf_debug.log"


# ── Canned state JSON (for `setstate <shortcut>`) ─────────────────────────────

CANNED_STATES: dict[str, dict] = {
    "empty": {"kind": "empty"},
    "idle": {
        "kind": "idle",
        "preset": {
            "filename": "production_idm.json",
            "name": "production_idm",
            "displayName": "IDM Production",
            "version": "1.0.0",
            "paletteName": "warm_idm",
            "palettePreview": ["#FF3A34", "#5480E4", "#FFA529", "#009D7A"],
            "targetCount": 11,
        },
        "source": {
            "filename": "sketch_04",
            "type": "manifest",
            "bpm": 112.4,
            "bars": 32,
            "stemCount": 4,
        },
    },
    "forging": {
        "kind": "forging",
        "preset": {
            "filename": "production_idm.json",
            "name": "production_idm",
            "displayName": "IDM Production",
            "version": "1.0.0",
            "paletteName": "warm_idm",
            "palettePreview": ["#FF3A34", "#5480E4"],
            "targetCount": 11,
        },
        "source": {
            "filename": "sketch_04",
            "type": "manifest",
            "bpm": 112.4,
            "bars": 32,
            "stemCount": 4,
        },
        "phase1": {
            "active": True,
            "progress": 0.42,
            "etaSec": 12,
            "stems": {
                "drums": "done",
                "bass": "splitting",
                "vocals": "pending",
                "other": "pending",
            },
            "engineLabel": "htdemucs_ft",
            "currentOp": "separating bass",
        },
        "phase2": {
            "active": False,
            "targetsTotal": 11,
            "targetsDone": 0,
            "targets": {},
            "currentOp": "",
        },
    },
    "done": {
        "kind": "done",
        "preset": {
            "filename": "production_idm.json",
            "name": "production_idm",
            "displayName": "IDM Production",
            "version": "1.0.0",
            "paletteName": "warm_idm",
            "palettePreview": ["#FF3A34"],
            "targetCount": 11,
        },
        "source": {
            "filename": "sketch_04",
            "type": "manifest",
            "bpm": 112.4,
            "bars": 32,
            "stemCount": 4,
        },
        "tracksCreated": 11,
        "trackRange": [4, 15],
        "elapsedSec": 38.2,
    },
    "error": {
        "kind": "error",
        "preset": {
            "filename": "production_idm.json",
            "name": "production_idm",
            "displayName": "IDM Production",
            "version": "1.0.0",
            "paletteName": "warm_idm",
            "palettePreview": ["#FF3A34"],
            "targetCount": 11,
        },
        "source": {
            "filename": "sketch_04",
            "type": "manifest",
            "bpm": 112.4,
            "bars": 32,
            "stemCount": 4,
        },
        "error": {
            "phase": 1,
            "kind": "split_failed",
            "message": "htdemucs_ft crashed on bass",
            "fix": "try the fused variant",
        },
    },
}


# ── UDP helpers ──────────────────────────────────────────────────────────────


def _send_udp(port: int, payload: str) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(payload.encode("utf-8"), (UDP_HOST, port))
    finally:
        sock.close()


def _send_bus(target: str, args: list[str]) -> None:
    """Send `<target> <args...>` to UDP 7420."""
    parts = [target] + list(args)
    msg = " ".join(str(p) for p in parts)
    _send_udp(UDP_BUS_PORT, msg)


def _send_dump(dict_name: str) -> None:
    """Send `dumpDict <name>` to UDP 7421 (→ sf_state_mgr)."""
    _send_udp(UDP_DUMP_PORT, f"dumpDict {dict_name}")


# ── Log tailing ──────────────────────────────────────────────────────────────


def _ensure_log_exists() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.touch()


def _tail(path: Path, *, follow: bool, initial_lines: int = 200) -> None:
    """Print the tail of `path`. Optionally follow (like `tail -f`)."""
    _ensure_log_exists()
    # Print initial backlog first.
    if path.exists():
        with path.open("r", encoding="utf-8", errors="replace") as f:
            backlog = f.readlines()
        for line in backlog[-initial_lines:]:
            sys.stdout.write(line)
        sys.stdout.flush()
    if not follow:
        return
    # Now follow.
    with path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        try:
            while True:
                chunk = f.read()
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                else:
                    time.sleep(0.2)
        except KeyboardInterrupt:
            sys.stdout.write("\n")
            sys.stdout.flush()


def _tail_until_marker(
    path: Path, marker: str, *, timeout: float = 5.0
) -> list[str]:
    """Follow `path` from its end until we see a line containing `marker`.

    Returns all lines from the starting position up to and including the
    marker line. Returns [] on timeout.
    """
    _ensure_log_exists()
    with path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        start_pos = f.tell()
        deadline = time.time() + timeout
        buf: list[str] = []
        while time.time() < deadline:
            chunk = f.read()
            if chunk:
                buf.extend(chunk.splitlines(keepends=True))
                if any(marker in line for line in buf):
                    # Trim to the marker line (inclusive).
                    out: list[str] = []
                    for line in buf:
                        out.append(line)
                        if marker in line:
                            return out
            else:
                time.sleep(0.1)
    return []


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_log(args: argparse.Namespace) -> int:
    if args.clear:
        # Truncate locally AND tell the running sf_logger.js to clear too
        # so both ends stay in sync.
        _ensure_log_exists()
        LOG_PATH.write_text("")
        _send_bus("logger", ["clear"])
        print(f"cleared {LOG_PATH}")
        return 0
    _tail(LOG_PATH, follow=args.follow)
    return 0


def cmd_fire(args: argparse.Namespace) -> int:
    target = args.target
    allowed = {
        "state", "forge", "preset-loader", "manifest-loader",
        "settings", "ui", "logger",
    }
    if target not in allowed:
        print(
            f"error: target '{target}' not in {sorted(allowed)}",
            file=sys.stderr,
        )
        return 2
    body = args.message or []
    _send_bus(target, body)
    print(f"→ {UDP_HOST}:{UDP_BUS_PORT}  {target} {' '.join(body)}")
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    name = args.dictname
    allowed = {"sf_state", "sf_preset", "sf_manifest", "sf_settings"}
    if name not in allowed:
        print(f"error: dict '{name}' not in {sorted(allowed)}", file=sys.stderr)
        return 2
    marker_tag = f"DUMP:{name}"
    end_marker = "DUMP END"
    _send_dump(name)
    # Wait for "DUMP END" from the module that matches DUMP:<name>.
    # We collect lines from the log starting after the send.
    lines = _tail_until_marker(
        LOG_PATH,
        marker=end_marker,
        timeout=args.timeout,
    )
    if not lines:
        print(
            f"timed out after {args.timeout}s waiting for '{end_marker}' — "
            f"is Max running the debug patch?",
            file=sys.stderr,
        )
        return 1
    relevant = [ln for ln in lines if marker_tag in ln]
    if not relevant:
        print(
            f"saw '{end_marker}' but no lines tagged '{marker_tag}'",
            file=sys.stderr,
        )
        return 1
    for line in relevant:
        sys.stdout.write(line)
    sys.stdout.flush()
    return 0


def cmd_setstate(args: argparse.Namespace) -> int:
    arg = args.target
    if arg in CANNED_STATES:
        payload = json.dumps(CANNED_STATES[arg])
    else:
        path = Path(arg)
        if not path.exists():
            print(
                f"error: '{arg}' is not a canned shortcut "
                f"({', '.join(CANNED_STATES)}) and not a file path",
                file=sys.stderr,
            )
            return 2
        payload = path.read_text()
        # Validate early so we don't send garbage over UDP.
        try:
            json.loads(payload)
        except json.JSONDecodeError as exc:
            print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
            return 2
    # setState is routed to the v8ui via target `ui`.
    # Build one flat string: "ui setState {...}" with the JSON inline.
    # UDP packets tolerate large payloads up to ~64KB; our state objects are
    # a few hundred bytes.
    _send_udp(UDP_BUS_PORT, f"ui setState {payload}")
    print(f"→ ui setState (kind={json.loads(payload).get('kind', '?')})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    # Print version, last N log lines, and current sf_state dump.
    n = args.lines
    print("=== sf_remote status ===")
    print(f"log path: {LOG_PATH}")
    print(f"udp host: {UDP_HOST}")
    print(f"bus port: {UDP_BUS_PORT}  dump port: {UDP_DUMP_PORT}")
    print("")
    print(f"--- last {n} log lines ---")
    _ensure_log_exists()
    if LOG_PATH.exists():
        lines = LOG_PATH.read_text(errors="replace").splitlines()
        for line in lines[-n:]:
            print(line)
    else:
        print("(no log yet)")
    print("")
    print("--- sf_state dump ---")
    args2 = argparse.Namespace(dictname="sf_state", timeout=3.0)
    cmd_dump(args2)
    return 0


# ── Argparse ─────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="sf-remote",
        description="Headless remote debug for the StemForge M4L device.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # log
    p_log = sub.add_parser("log", help="Tail or clear the debug log.")
    p_log.add_argument(
        "--follow", "-f", action="store_true",
        help="Follow new log lines (like tail -f).",
    )
    p_log.add_argument(
        "--clear", action="store_true",
        help="Truncate the log locally AND send 'clear' via UDP to sf_logger.",
    )
    p_log.set_defaults(func=cmd_log)

    # fire
    p_fire = sub.add_parser(
        "fire",
        help=(
            "Send a UDP message to a module. "
            "targets: state forge preset-loader manifest-loader settings ui logger"
        ),
    )
    p_fire.add_argument(
        "target",
        help="Module target (state / forge / preset-loader / manifest-loader / settings / ui / logger).",
    )
    p_fire.add_argument(
        "message", nargs=argparse.REMAINDER,
        help="Message body (one or more atoms). E.g. markStemDone bass",
    )
    p_fire.set_defaults(func=cmd_fire)

    # dump
    p_dump = sub.add_parser(
        "dump",
        help="Dump a dict into the log via port 7421 and print the captured block.",
    )
    p_dump.add_argument(
        "dictname",
        help="Dict name (sf_state | sf_preset | sf_manifest | sf_settings).",
    )
    p_dump.add_argument(
        "--timeout", type=float, default=3.0,
        help="Seconds to wait for DUMP END marker (default 3).",
    )
    p_dump.set_defaults(func=cmd_dump)

    # setstate
    p_set = sub.add_parser(
        "setstate",
        help=(
            "Push sf_state JSON into the v8ui (shortcuts: "
            f"{', '.join(CANNED_STATES)}). You may also pass a JSON file path."
        ),
    )
    p_set.add_argument(
        "target",
        help="Shortcut name or path to a .json file.",
    )
    p_set.set_defaults(func=cmd_setstate)

    # status
    p_status = sub.add_parser(
        "status",
        help="Print last N log lines + dump sf_state.",
    )
    p_status.add_argument(
        "--lines", "-n", type=int, default=60,
        help="How many log lines to print (default 60).",
    )
    p_status.set_defaults(func=cmd_status)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
