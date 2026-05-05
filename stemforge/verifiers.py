"""Structural verifiers for StemForge.amxd (Hardening Stream C.2).

Vendored from the external harness at
``~/raindog/harness/quickstarts/max-plugin/tools/forge_device/verifiers.py``
(harness commit ``26f4d02``). Each verifier is a pure function: takes a
target (patcher dict, .amxd path) and returns a ``Result``. The fork point
is recorded in ``_HARNESS_VERSION``; bumping this constant + diffing
against the upstream file is how stemforge keeps the vendor in step.

Each verifier encodes one of the 20 hard-won M4L pitfalls documented at
``memory/m4l_device_development_guide.md``. Fix-hints are LLM-actionable
strings: a failing verifier returns a structured Result whose ``fix_hint``
field tells the next agent (or human) what to do.

Usage::

    python -m stemforge.verifiers verify-amxd v0/build/StemForge.amxd
    python -m stemforge.verifiers verify-patcher <unpacked.json>

Programmatic::

    from stemforge.verifiers import run_all
    results = run_all(amxd_path, kind="amxd")
    for r in results:
        print(r.passed, r.verifier, r.detail)

CI integration (non-blocking) is wired in ``.github/workflows/ci.yml``;
see the ``verify-amxd`` step.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Vendor reference — harness commit this verifiers module was last synced
# from. Re-vendor with the same procedure documented in stemforge/audit.py.
_HARNESS_VERSION = "26f4d02"


@dataclass
class Result:
    """A single verifier result.

    Fields are stable across runs; downstream agents (or CI dashboards)
    can rely on the shape. ``fix_hint`` is meant to be LLM-actionable.
    """

    verifier: str
    passed: bool
    pitfall: str | None = None  # e.g., "#7" — links to dev guide
    detail: str = ""
    fix_hint: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _box_text(box: dict[str, Any]) -> str:
    body = box.get("box", {})
    return str(body.get("text", "") or body.get("maxclass", ""))


def _has_box(boxes: list[dict[str, Any]], predicate: Callable[[dict], bool]) -> bool:
    return any(predicate(b) for b in boxes)


# ── Patcher-level verifiers ──────────────────────────────────────────────────


def verify_project_field(patcher_dict: dict[str, Any]) -> Result:
    """Pitfall #6: Max prints 'fatal' if `project` field is missing or
    `project.amxdtype` is not 1633771873."""
    p = patcher_dict.get("patcher", {})
    proj = p.get("project")
    if not proj:
        return Result(
            "project_field_present",
            False,
            "#6",
            "patcher missing `project` field",
            "use stemforge_bridge.patcher.empty_patcher() — it sets this",
        )
    if proj.get("amxdtype") != 1633771873:
        return Result(
            "project_field_present",
            False,
            "#6",
            f"patcher.project.amxdtype = {proj.get('amxdtype')!r}, must be 1633771873",
            "set project.amxdtype = patcher.AMXD_PROJECT_TYPE",
        )
    return Result("project_field_present", True, "#6")


def verify_plugin_pair_canonical_shape(patcher_dict: dict[str, Any]) -> Result:
    """Pitfall #27: `[plugin~]` and `[plugout~]` boxes must match Live's
    canonical M4L template shape exactly."""
    p = patcher_dict.get("patcher", {})
    boxes = p.get("boxes", [])
    issues: list[str] = []
    for b in boxes:
        bx = b.get("box", {})
        text = bx.get("text", "")
        for kind in ("plugin~", "plugout~"):
            if text == kind or text.startswith(kind + " "):
                if text != kind:
                    issues.append(f"{bx.get('id')}: text={text!r}, must be {kind!r} (no arg)")
                if bx.get("numinlets") != 2:
                    issues.append(f"{bx.get('id')}: numinlets={bx.get('numinlets')}, must be 2")
                if bx.get("numoutlets") != 2:
                    issues.append(f"{bx.get('id')}: numoutlets={bx.get('numoutlets')}, must be 2")
                if bx.get("outlettype") != ["signal", "signal"]:
                    issues.append(
                        f"{bx.get('id')}: outlettype={bx.get('outlettype')!r}, "
                        "must be ['signal','signal']"
                    )
                break
    if issues:
        return Result(
            "plugin_pair_canonical_shape",
            False,
            "#27",
            "; ".join(issues),
            "use plugin_in()/plugin_out() helpers (canonical shape)",
        )
    return Result("plugin_pair_canonical_shape", True, "#27")


def verify_inlet_outlet_indices(patcher_dict: dict[str, Any]) -> Result:
    """Pitfall #26: Subpatcher `[inlet]` / `[outlet]` boxes must carry
    explicit 0-based `index` attributes forming a contiguous {0..N-1} set."""

    def _check(boxes: list, kind: str) -> str | None:
        these = [b["box"] for b in boxes if b.get("box", {}).get("maxclass") == kind]
        if not these:
            return None
        indices = [b.get("index") for b in these]
        if any(idx is None or not isinstance(idx, int) for idx in indices):
            return f"{kind} box(es) missing integer `index` attribute: {indices}"
        n = len(these)
        if sorted(indices) != list(range(n)):
            return (
                f"{kind} indices {sorted(indices)} not contiguous {{0..{n - 1}}} — "
                "likely 1-based or has gaps"
            )
        sorted_by_idx = sorted(these, key=lambda b: b["index"])
        xs = [b.get("patching_rect", [0])[0] for b in sorted_by_idx]
        if xs != sorted(xs) or len(set(xs)) != len(xs):
            return (
                f"{kind} patching_rect[0] X-coords {xs} not strictly monotonic "
                "in index order — Max's spatial fallback will assign indices wrong"
            )
        return None

    def _walk(p: dict, path: str) -> list[str]:
        errs = []
        boxes = p.get("boxes", [])
        for kind in ("inlet", "outlet"):
            err = _check(boxes, kind)
            if err:
                errs.append(f"{path}: {err}")
        for b in boxes:
            sub = b.get("box", {}).get("patcher")
            if sub:
                bid = b.get("box", {}).get("id", "?")
                errs.extend(_walk(sub, f"{path}.{bid}"))
        return errs

    root = patcher_dict.get("patcher", {})
    errs = _walk(root, "patcher")
    if errs:
        suffix = f"; +{len(errs) - 5} more" if len(errs) > 5 else ""
        return Result(
            "inlet_outlet_indices",
            False,
            "#26",
            "; ".join(errs[:5]) + suffix,
            "use 0-based `idx` in inlet_box/outlet_box; ensure X-coords are monotonic",
        )
    return Result("inlet_outlet_indices", True, "#26")


def verify_project_searchpath(patcher_dict: dict[str, Any]) -> Result:
    """Pitfall #25: Live's M4L runtime calls `project_deserialize_searchpath`
    unconditionally during `.amxd` load. If `project.searchpath` is missing,
    Live segfaults before any boxes are created."""
    p = patcher_dict.get("patcher", {})
    proj = p.get("project") or {}
    sp = proj.get("searchpath")
    if not isinstance(sp, dict):
        return Result(
            "project_searchpath_present",
            False,
            "#25",
            f"patcher.project.searchpath is {type(sp).__name__}, must be a dict (even empty {{}})",
            "make_patcher_skeleton emits the canonical project shape",
        )
    return Result("project_searchpath_present", True, "#25")


def verify_plugin_pair_for_audio(
    patcher_dict: dict[str, Any], *, device_class: str = "audio"
) -> Result:
    """Pitfall #7: audio effects MUST include `[plugin~ N]` and `[plugout~ N]`
    or Ableton silently rejects the device."""
    if device_class != "audio":
        return Result("plugin_pair_required", True, "#7", "n/a (not audio class)")
    boxes = patcher_dict.get("patcher", {}).get("boxes", [])
    has_plugin = _has_box(boxes, lambda b: _box_text(b).startswith("plugin~"))
    has_plugout = _has_box(boxes, lambda b: _box_text(b).startswith("plugout~"))
    if not has_plugin:
        return Result(
            "plugin_pair_required",
            False,
            "#7",
            "audio device missing `plugin~` box",
            "patcher.plugin_in() returns the correct box",
        )
    if not has_plugout:
        return Result(
            "plugin_pair_required",
            False,
            "#7",
            "audio device missing `plugout~` box",
            "patcher.plugin_out() returns the correct box",
        )
    return Result("plugin_pair_required", True, "#7")


def verify_no_node_script(patcher_dict: dict[str, Any]) -> Result:
    """Pitfall #1: `node.script` is broken on macOS 26+ when launched from
    Live (Team ID mismatch under hardened runtime). Use `[shell]` + `[js]`."""
    boxes = patcher_dict.get("patcher", {}).get("boxes", [])
    bad = [b for b in boxes if "node.script" in _box_text(b)]
    if bad:
        return Result(
            "no_node_script",
            False,
            "#1",
            f"found {len(bad)} `node.script` box(es) — broken on macOS 26+",
            "replace with `[shell]` + `[js]` pair",
        )
    return Result("no_node_script", True, "#1")


def verify_no_static_comment_for_dynamic(patcher_dict: dict[str, Any]) -> Result:
    """Pitfall #3: `[comment]` ignores `set` messages. For runtime text use
    `[live.comment]`. Flag suspicious `[comment]` boxes wired to a source."""
    boxes = patcher_dict.get("patcher", {}).get("boxes", [])
    lines = patcher_dict.get("patcher", {}).get("lines", [])
    comment_ids = {b["box"]["id"] for b in boxes if b.get("box", {}).get("maxclass") == "comment"}
    wired_comment_ids = set()
    for ln in lines:
        dst = ln.get("patchline", {}).get("destination", [None])
        if dst[0] in comment_ids:
            wired_comment_ids.add(dst[0])
    if wired_comment_ids:
        return Result(
            "no_static_comment_for_dynamic",
            False,
            "#3",
            f"`[comment]` boxes receiving messages: {sorted(wired_comment_ids)}",
            "swap [comment] → [live.comment]",
        )
    return Result("no_static_comment_for_dynamic", True, "#3")


def verify_live_dial_param_attrs(patcher_dict: dict[str, Any]) -> Result:
    """Pitfall #18: `[live.dial]` without full `saved_attribute_attributes`
    silently fails to expose the param to Live automation."""
    boxes = patcher_dict.get("patcher", {}).get("boxes", [])
    bad = []
    for b in boxes:
        body = b.get("box", {})
        if body.get("maxclass") == "live.dial":
            saa = body.get("saved_attribute_attributes", {})
            valueof = saa.get("valueof", {})
            required = ["parameter_longname", "parameter_mmin", "parameter_mmax"]
            missing = [k for k in required if k not in valueof]
            if missing:
                bad.append((body.get("id"), missing))
    if bad:
        return Result(
            "live_dial_param_attrs",
            False,
            "#18",
            f"{len(bad)} live.dial box(es) missing required param attrs: {bad[:3]}",
            "use patcher.live_dial(...) — it sets the full saved_attribute_attributes",
        )
    return Result("live_dial_param_attrs", True, "#18")


def verify_umenu_items_format(patcher_dict: dict[str, Any]) -> Result:
    """Pitfall #5: `[umenu]` items must be space-separated. Comma-separated
    items become one big merged item silently."""
    boxes = patcher_dict.get("patcher", {}).get("boxes", [])
    bad = []
    for b in boxes:
        body = b.get("box", {})
        if body.get("maxclass") == "umenu":
            items = body.get("items") or body.get("@items")
            if isinstance(items, str) and "," in items:
                bad.append(body.get("id"))
    if bad:
        return Result(
            "umenu_items_space_separated",
            False,
            "#5",
            f"{len(bad)} umenu box(es) have comma-separated items: {bad}",
            "switch separator: 'a,b,c' → 'a b c'",
        )
    return Result("umenu_items_space_separated", True, "#5")


# ── .amxd container verifiers ────────────────────────────────────────────────


def verify_amxd_magic(amxd_path: str | Path) -> Result:
    """Pitfall #14: container header sentinel determines device class.
    `b'aaaa'` for audio, `b'mmmm'` for midi, `b'iiii'` for instrument."""
    raw = Path(amxd_path).read_bytes()
    if raw[:4] != b"ampf":
        return Result(
            "amxd_magic",
            False,
            "#14",
            f"missing 'ampf' magic at offset 0: {raw[:4]!r}",
            "",
        )
    sentinel = raw[8:12]
    if sentinel not in (b"aaaa", b"mmmm", b"iiii"):
        return Result(
            "amxd_magic",
            False,
            "#14",
            f"unknown class sentinel at offset 8: {sentinel!r}",
            "use amxd_pack.pack_amxd(..., device_class='audio'|'midi'|'instrument')",
        )
    return Result("amxd_magic", True, "#14", detail=f"sentinel={sentinel.decode()}")


def verify_amxd_round_trip(amxd_path: str | Path) -> Result:
    """The .amxd binary unpacks back to a valid patcher dict.

    Skips cleanly if the project's amxd_pack helper isn't importable
    (e.g., running from a clean checkout that doesn't expose v0/).
    """
    try:
        amxd_pack = _import_amxd_pack()
    except ImportError as e:
        return Result(
            "amxd_round_trip",
            True,
            None,
            f"skipped (amxd_pack unavailable: {e})",
            "",
        )
    try:
        result = amxd_pack.unpack_amxd(amxd_path)
        if "patcher" not in result.get("patcher", {}):
            return Result(
                "amxd_round_trip",
                False,
                None,
                "unpacked .amxd lacks 'patcher' key",
                "",
            )
        return Result(
            "amxd_round_trip",
            True,
            None,
            f"unpacked OK; device_type={result.get('device_type', '?')}",
        )
    except Exception as e:
        return Result(
            "amxd_round_trip",
            False,
            None,
            f"unpack failed: {e}",
            "regenerate via amxd_pack.pack_amxd",
        )


def _import_amxd_pack():  # type: ignore[no-untyped-def]
    """Import the project's amxd_pack helper, falling back across known paths."""
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / "v0" / "src" / "maxpat-builder",
    ]
    for c in candidates:
        if (c / "amxd_pack.py").exists():
            sys.path.insert(0, str(c))
            try:
                import amxd_pack  # type: ignore[import-not-found]

                return amxd_pack
            finally:
                # Don't pollute sys.path long-term.
                if str(c) in sys.path:
                    sys.path.remove(str(c))
    raise ImportError("amxd_pack not found in known locations")


# ── Registries ───────────────────────────────────────────────────────────────


PATCHER_VERIFIERS: list[Callable[..., Result]] = [
    verify_project_field,
    verify_project_searchpath,
    verify_inlet_outlet_indices,
    verify_plugin_pair_for_audio,
    verify_plugin_pair_canonical_shape,
    verify_no_node_script,
    verify_no_static_comment_for_dynamic,
    verify_live_dial_param_attrs,
    verify_umenu_items_format,
]

AMXD_VERIFIERS: list[Callable[[str | Path], Result]] = [
    verify_amxd_magic,
    verify_amxd_round_trip,
]


def run_all(target: Any, *, kind: str) -> list[Result]:
    """Run all verifiers for ``kind``. Returns list of Results (pass + fail).

    Currently supported kinds: ``patcher`` (dict), ``amxd`` (path).
    """
    if kind == "patcher":
        return [v(target) for v in PATCHER_VERIFIERS]
    if kind == "amxd":
        # Run the .amxd-level checks plus, when round-trip succeeds, run the
        # patcher-level checks against the unpacked patcher dict.
        results = [v(target) for v in AMXD_VERIFIERS]
        try:
            amxd_pack = _import_amxd_pack()
            unpacked = amxd_pack.unpack_amxd(target)
            patcher = unpacked.get("patcher", {})
            results.extend(v(patcher) for v in PATCHER_VERIFIERS)
        except (ImportError, Exception) as e:
            results.append(
                Result(
                    "amxd_unpack_for_patcher_checks",
                    True,
                    None,
                    f"skipped patcher-level checks: {e}",
                    "",
                )
            )
        return results
    raise ValueError(f"unknown verifier kind: {kind}")


# ── CLI entry point ──────────────────────────────────────────────────────────


def _format_result(r: Result) -> str:
    icon = "✓" if r.passed else "✗"
    parts = [f"{icon} {r.verifier}"]
    if r.pitfall:
        parts.append(f"({r.pitfall})")
    if r.detail:
        parts.append(f"— {r.detail}")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stemforge.verifiers")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_amxd = sub.add_parser("verify-amxd", help="Run all verifiers on a .amxd file")
    p_amxd.add_argument("path", type=Path)
    p_amxd.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args(argv)

    if args.cmd == "verify-amxd":
        results = run_all(args.path, kind="amxd")
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "verifier": r.verifier,
                            "passed": r.passed,
                            "pitfall": r.pitfall,
                            "detail": r.detail,
                            "fix_hint": r.fix_hint,
                        }
                        for r in results
                    ],
                    indent=2,
                )
            )
        else:
            for r in results:
                print(_format_result(r))
                if r.fix_hint and not r.passed:
                    print(f"    fix: {r.fix_hint}")
        return 0 if all(r.passed for r in results) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AMXD_VERIFIERS",
    "PATCHER_VERIFIERS",
    "Result",
    "run_all",
    "verify_amxd_magic",
    "verify_amxd_round_trip",
    "verify_inlet_outlet_indices",
    "verify_live_dial_param_attrs",
    "verify_no_node_script",
    "verify_no_static_comment_for_dynamic",
    "verify_plugin_pair_canonical_shape",
    "verify_plugin_pair_for_audio",
    "verify_project_field",
    "verify_project_searchpath",
    "verify_umenu_items_format",
]
