"""Build StemForge.als from skeleton.als + tracks.yaml.

Entry point: `python -m als_builder.builder` or `als_builder.builder:build()`.

See `v0/tracks/D-als-template.md` for the brief. High-level flow:

    skeleton.als (gzipped XML)
        │
        ├── lxml parse
        │
        ├── discover template <AudioTrack> / <MidiTrack> from the skeleton
        │     (fallback: synthesize a minimal one if absent)
        │
        ├── for each track in tracks.yaml:
        │       clone template → set Name/ColorIndex
        │                      → populate device chain
        │                      → append to <Tracks>
        │
        ├── renumber every Id="…" attribute set-wide
        │
        └── write StemForge.als (gzipped XML, xml_declaration=True, UTF-8)
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - import error path
    raise SystemExit(
        "als-builder requires PyYAML. `uv pip install pyyaml` or add to "
        "v0/src/als-builder's dependency manifest."
    ) from exc

try:
    from lxml import etree as ET
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "als-builder requires lxml. `uv pip install lxml`."
    ) from exc

from colors import hex_to_color_index  # noqa: E402 — local module

# Paths — resolved relative to this module, not the CWD, so the tool works
# no matter where it's invoked from.
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent  # .../v0/src/als-builder → repo root
TRACKS_YAML = REPO_ROOT / "v0" / "interfaces" / "tracks.yaml"
SKELETON_ALS = REPO_ROOT / "v0" / "assets" / "skeleton.als"
OUTPUT_ALS = REPO_ROOT / "v0" / "build" / "StemForge.als"
DEVICES_DIR = HERE / "devices"
VST3_LOOKUP = HERE / "vst3_lookup.yaml"

# Max 70 — larger values will silently collapse to a valid index.
_DEFAULT_COLOR_IDX = 14  # red (safe fallback)


# --------------------------------------------------------------------- #
# YAML loading                                                          #
# --------------------------------------------------------------------- #


def load_tracks_spec(path: Path = TRACKS_YAML) -> dict[str, Any]:
    """Load and return the tracks.yaml document."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_vst3_lookup(path: Path = VST3_LOOKUP) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# --------------------------------------------------------------------- #
# Device fragment loading                                               #
# --------------------------------------------------------------------- #

# Canonical stock device XML files. Keys match `device:` values in
# tracks.yaml; extensions are added automatically.
STOCK_DEVICE_FILES = {
    "Compressor": "Compressor.xml",
    "EQ Eight": "Eq8.xml",
    "Reverb": "Reverb.xml",
    "Utility": "Utility.xml",
    "Simpler": "Simpler.xml",
}


def load_device_fragment(device_name: str) -> ET._Element:
    """Return a fresh parsed element-tree root for a stock device.

    A new element is returned on every call so callers may mutate freely.
    """
    filename = STOCK_DEVICE_FILES.get(device_name)
    if filename is None:
        raise KeyError(f"No stock device fragment registered for {device_name!r}")
    return ET.parse(str(DEVICES_DIR / filename)).getroot()


# --------------------------------------------------------------------- #
# Device parameter application                                          #
# --------------------------------------------------------------------- #


def _set_manual(elem: ET._Element, xpath: str, value: Any) -> None:
    """Set <.../Manual Value="…"/> at xpath (relative to elem)."""
    target = elem.find(xpath)
    if target is None:
        return  # Missing field — ignore; Live will fill defaults.
    target.set("Value", _yaml_to_live_value(value))


def _yaml_to_live_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        # Preserve integer-ness to match Live's on-disk style.
        if float(v).is_integer():
            return str(int(v))
        return repr(float(v))
    return str(v)


def apply_compressor_params(elem: ET._Element, params: dict[str, Any]) -> None:
    if "threshold_db" in params:
        _set_manual(elem, "./Threshold/Manual", params["threshold_db"])
    if "ratio" in params:
        _set_manual(elem, "./Ratio/Manual", params["ratio"])
    if "attack_ms" in params:
        _set_manual(elem, "./Attack/Manual", params["attack_ms"])
    if "release_ms" in params:
        _set_manual(elem, "./Release/Manual", params["release_ms"])


def apply_reverb_params(elem: ET._Element, params: dict[str, Any]) -> None:
    # tracks.yaml expresses decay in seconds; Live stores ms.
    if "decay_sec" in params:
        _set_manual(elem, "./DecayTime/Manual", float(params["decay_sec"]) * 1000)
    if "diffusion" in params:
        _set_manual(elem, "./Diffusion/Manual", params["diffusion"])


def apply_utility_params(elem: ET._Element, params: dict[str, Any]) -> None:
    if "gain_db" in params:
        _set_manual(elem, "./Gain/Manual", params["gain_db"])


def apply_simpler_params(elem: ET._Element, params: dict[str, Any]) -> None:
    if "mode" in params:
        # slice=2, one_shot=1, classic=0
        mode_map = {"classic": 0, "one_shot": 1, "slice": 2}
        v = mode_map.get(str(params["mode"]).lower(), 2)
        _set_manual(elem, "./Playback/PlayMode/Manual", v)
    if "warp" in params:
        warp = params["warp"]
        if isinstance(warp, str):
            warp = warp.lower() in ("on", "true", "yes", "1")
        _set_manual(elem, "./Player/Warping/Manual", bool(warp))


STOCK_PARAM_APPLIERS = {
    "Compressor": apply_compressor_params,
    "EQ Eight": lambda e, p: None,  # flat default for v0
    "Reverb": apply_reverb_params,
    "Utility": apply_utility_params,
    "Simpler": apply_simpler_params,
}


def build_stock_device(device_name: str, params: dict[str, Any]) -> ET._Element:
    elem = load_device_fragment(device_name)
    applier = STOCK_PARAM_APPLIERS.get(device_name, lambda e, p: None)
    applier(elem, params)
    return elem


# --------------------------------------------------------------------- #
# VST3 emission                                                         #
# --------------------------------------------------------------------- #


def build_vst3_missing_placeholder(
    device_name: str, params: dict[str, Any]
) -> ET._Element:
    """Emit a Live-compatible missing-plugin placeholder.

    Live 12 renders sets with unrecognized VST3 UIDs as a visible
    "Plugin missing" device. The XML is an <Vst3PluginDevice> node with
    the Name set; the user sees the banner and can re-point it.

    We embed the YAML params as a JSON blob in <UserDisplayName> so the
    user can recover their intent after installing the plugin.
    """
    import json

    dev = ET.Element("Vst3PluginDevice", Id="0")
    ET.SubElement(dev, "LomId", Value="0")
    on = ET.SubElement(dev, "On")
    ET.SubElement(on, "LomId", Value="0")
    ET.SubElement(on, "Manual", Value="true")
    ET.SubElement(dev, "UserDisplayName", Value=f"{device_name} [params={json.dumps(params)}]")
    ET.SubElement(dev, "Uid", Value="00000000000000000000000000000000")
    ET.SubElement(dev, "Name", Value=device_name)
    ET.SubElement(dev, "PluginDesc")  # empty — Live treats as missing
    return dev


def build_vst3_device(
    device_name: str,
    params: dict[str, Any],
    vst3_lookup: dict[str, Any],
) -> ET._Element:
    """Emit a Vst3PluginDevice node populated from the lookup table.

    If the plugin is not in the lookup table, emit a missing-plugin
    placeholder (Live 12 handles this gracefully — see D-als-template.md §D6).
    """
    entry = vst3_lookup.get(device_name)
    if entry is None:
        return build_vst3_missing_placeholder(device_name, params)

    dev = ET.Element("Vst3PluginDevice", Id="0")
    ET.SubElement(dev, "LomId", Value="0")
    on = ET.SubElement(dev, "On")
    ET.SubElement(on, "LomId", Value="0")
    ET.SubElement(on, "Manual", Value="true")
    ET.SubElement(dev, "UserDisplayName", Value="")
    ET.SubElement(dev, "Uid", Value=entry["uid"])
    ET.SubElement(dev, "Name", Value=entry.get("name", device_name))
    ET.SubElement(dev, "Vendor", Value=entry.get("vendor", ""))

    plist = ET.SubElement(dev, "ParameterList")
    for yaml_key, yaml_val in params.items():
        spec = entry.get("params", {}).get(yaml_key)
        if spec is None:
            continue  # unknown param — skip
        pid = spec["id"]
        normalized = _normalize_vst3_param_value(yaml_val, spec)
        param = ET.SubElement(plist, "Parameter")
        ET.SubElement(param, "Id", Value=str(pid))
        ET.SubElement(param, "Value", Value=repr(float(normalized)))
    return dev


def _normalize_vst3_param_value(val: Any, spec: dict[str, Any]) -> float:
    """Convert a tracks.yaml value to a VST3-native normalized 0..1 float.

    Supports:
      - enum strings (via `spec.enum`)
      - pitch strings like "+5 semitones" in a signed-range spec
      - floats already in spec.range, mapped to 0..1
      - ints (same)
    """
    enum = spec.get("enum") if isinstance(spec, dict) else None
    rng = spec.get("range") if isinstance(spec, dict) else None

    if isinstance(val, str) and enum and val in enum:
        val = enum[val]
    elif isinstance(val, str):
        # Try "+5 semitones" style.
        stripped = val.strip()
        if stripped.endswith("semitones") or stripped.endswith("semitone"):
            try:
                val = float(stripped.split()[0])
            except Exception:
                val = 0.0
        else:
            try:
                val = float(stripped)
            except Exception:
                val = 0.0

    val = float(val)
    if rng and isinstance(rng, (list, tuple)) and len(rng) == 2:
        lo, hi = float(rng[0]), float(rng[1])
        if hi != lo:
            return max(0.0, min(1.0, (val - lo) / (hi - lo)))
    return max(0.0, min(1.0, val))


# --------------------------------------------------------------------- #
# Track assembly                                                        #
# --------------------------------------------------------------------- #


def _set_name(track_el: ET._Element, name: str) -> None:
    # Live's AudioTrack/MidiTrack carry name under Name/EffectiveName/Value
    # and Name/UserName/Value. We set both so Live picks it up regardless of
    # schema point-release differences.
    for xpath in ("./Name/EffectiveName", "./Name/UserName"):
        el = track_el.find(xpath)
        if el is not None:
            el.set("Value", name)


def _set_color_index(track_el: ET._Element, hex_color: str) -> None:
    idx = hex_to_color_index(hex_color)
    # Live writes ColorIndex as a direct child of the track node.
    ci = track_el.find("./ColorIndex")
    if ci is None:
        ci = ET.SubElement(track_el, "ColorIndex")
    ci.set("Value", str(idx))


def _find_device_chain_devices(track_el: ET._Element) -> ET._Element:
    """Return the <Devices> container inside a track's main device chain.

    The Live 12 path is typically:
      AudioTrack/DeviceChain/DeviceChain/Devices
    (yes, nested — the outer is the track's IO chain, the inner is the
    device chain proper).
    """
    # Prefer the nested DeviceChain/DeviceChain/Devices path.
    devices = track_el.find("./DeviceChain/DeviceChain/Devices")
    if devices is None:
        # Fallback: any descendant <Devices>.
        devices = track_el.find(".//Devices")
    if devices is None:
        # Synthesize the path as a last resort so the builder doesn't crash
        # on malformed skeletons.
        outer = ET.SubElement(track_el, "DeviceChain")
        inner = ET.SubElement(outer, "DeviceChain")
        devices = ET.SubElement(inner, "Devices")
    return devices


def _clear_device_chain(track_el: ET._Element) -> None:
    devices = _find_device_chain_devices(track_el)
    for child in list(devices):
        devices.remove(child)


def build_device_chain(
    track_el: ET._Element,
    chain_spec: list[dict[str, Any]],
    vst3_lookup: dict[str, Any],
) -> None:
    """Populate the track's device chain from the chain spec."""
    _clear_device_chain(track_el)
    devices = _find_device_chain_devices(track_el)
    for item in chain_spec:
        device_name = item["device"]
        params = item.get("params", {}) or {}
        if device_name in STOCK_DEVICE_FILES:
            devices.append(build_stock_device(device_name, params))
        else:
            devices.append(build_vst3_device(device_name, params, vst3_lookup))


# --------------------------------------------------------------------- #
# Skeleton track discovery + cloning                                    #
# --------------------------------------------------------------------- #


def _find_template_track(
    root: ET._Element, kind: str
) -> ET._Element | None:
    """Find a single <AudioTrack> or <MidiTrack> in the skeleton to clone."""
    if kind == "audio":
        return root.find(".//AudioTrack")
    if kind == "midi":
        return root.find(".//MidiTrack")
    raise ValueError(f"Unknown track kind: {kind!r}")


def _synthesize_track(kind: str) -> ET._Element:
    """Minimal synthesized track for skeletons that lack one.

    NOTE: Live may refuse to open a truly minimal track — this is a last-
    resort fallback. The recommended path is for skeleton.als to be a
    Live 12 set that already contains one AudioTrack and one MidiTrack.
    """
    tag = "AudioTrack" if kind == "audio" else "MidiTrack"
    t = ET.Element(tag, Id="0")
    ET.SubElement(t, "LomId", Value="0")
    ET.SubElement(t, "LomIdView", Value="0")
    name = ET.SubElement(t, "Name")
    ET.SubElement(name, "EffectiveName", Value="")
    ET.SubElement(name, "UserName", Value="")
    ET.SubElement(name, "Annotation", Value="")
    ET.SubElement(t, "ColorIndex", Value=str(_DEFAULT_COLOR_IDX))
    outer = ET.SubElement(t, "DeviceChain")
    inner = ET.SubElement(outer, "DeviceChain")
    ET.SubElement(inner, "Devices")
    return t


def clone_track(
    root: ET._Element, kind: str
) -> ET._Element:
    """Deep-copy a skeleton track of the given kind, or synthesize one."""
    template = _find_template_track(root, kind)
    if template is not None:
        return _deepcopy(template)
    return _synthesize_track(kind)


def _deepcopy(elem: ET._Element) -> ET._Element:
    # lxml elements don't play nicely with copy.deepcopy across etree
    # implementations; serialize + reparse is bulletproof for moderate sizes.
    xml = ET.tostring(elem)
    return ET.fromstring(xml)


# --------------------------------------------------------------------- #
# Id renumbering                                                        #
# --------------------------------------------------------------------- #


def renumber_ids(root: ET._Element, start: int = 1) -> int:
    """Rewrite every Id attribute to be set-wide unique.

    Live uses a single monotonic Id counter spanning every <… Id="N"/> in
    the document. The strictest rule is uniqueness; contiguity is not
    required. We walk the tree and assign fresh IDs sequentially.

    Returns the next free ID (useful for round-tripping).
    """
    counter = start
    for el in root.iter():
        if "Id" in el.attrib:
            el.set("Id", str(counter))
            counter += 1
    return counter


# --------------------------------------------------------------------- #
# Main build                                                            #
# --------------------------------------------------------------------- #


def _find_tracks_container(root: ET._Element) -> ET._Element:
    """Locate <LiveSet>/<Tracks> (the container into which tracks go).

    lxml XPath varies across Live XML schema drift; we try two likely paths.
    """
    tracks = root.find(".//LiveSet/Tracks")
    if tracks is not None:
        return tracks
    tracks = root.find(".//Tracks")
    if tracks is not None:
        return tracks
    # Last resort: create <LiveSet><Tracks/></LiveSet>
    liveset = root.find(".//LiveSet")
    if liveset is None:
        liveset = ET.SubElement(root, "LiveSet")
    return ET.SubElement(liveset, "Tracks")


def build(
    skeleton_path: Path = SKELETON_ALS,
    tracks_yaml_path: Path = TRACKS_YAML,
    output_path: Path = OUTPUT_ALS,
    vst3_lookup_path: Path = VST3_LOOKUP,
) -> Path:
    """Build StemForge.als. Returns the output path on success.

    Raises FileNotFoundError if skeleton.als is missing — this is a
    deliberate hard stop (see D-als-template.md and v0/assets/README.md).
    """
    if not skeleton_path.exists():
        raise FileNotFoundError(
            f"skeleton.als missing at {skeleton_path}. This file is a "
            "one-time human-created asset — see v0/assets/README.md for "
            "instructions on producing it."
        )

    spec = load_tracks_spec(tracks_yaml_path)
    vst3_lookup = load_vst3_lookup(vst3_lookup_path)

    # Parse skeleton.
    with gzip.open(skeleton_path, "rb") as f:
        tree = ET.parse(f)
    root = tree.getroot()
    tracks_container = _find_tracks_container(root)

    # Remove any pre-existing tracks Live left in the skeleton so the
    # output is deterministic.
    for child in list(tracks_container):
        tracks_container.remove(child)

    for track_spec in spec["tracks"]:
        kind = track_spec["type"]  # "audio" or "midi"
        track_el = clone_track(root, kind)
        _set_name(track_el, track_spec["name"])
        _set_color_index(track_el, track_spec["color"])
        build_device_chain(
            track_el, track_spec.get("chain", []), vst3_lookup
        )
        tracks_container.append(track_el)

    # Fresh IDs for the whole document.
    renumber_ids(root)

    # Write gzipped.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = ET.tostring(
        tree, xml_declaration=True, encoding="UTF-8", standalone=False
    )
    with gzip.open(output_path, "wb") as f:
        f.write(xml_bytes)

    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build StemForge.als")
    parser.add_argument("--skeleton", type=Path, default=SKELETON_ALS)
    parser.add_argument("--tracks-yaml", type=Path, default=TRACKS_YAML)
    parser.add_argument("--output", type=Path, default=OUTPUT_ALS)
    parser.add_argument("--vst3-lookup", type=Path, default=VST3_LOOKUP)
    args = parser.parse_args(argv)
    try:
        out = build(
            skeleton_path=args.skeleton,
            tracks_yaml_path=args.tracks_yaml,
            output_path=args.output,
            vst3_lookup_path=args.vst3_lookup,
        )
    except FileNotFoundError as e:
        print(f"BLOCKER: {e}", file=sys.stderr)
        return 2
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
