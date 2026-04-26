"""Assemble an EP-133 K.O. II ``.ppak`` from a :class:`PpakSpec`.

The ``.ppak`` is a ZIP wrapper around an inner POSIX TAR (no compression
on the TAR; the ZIP entries are deflated). The TAR holds:

    pads/{a,b,c,d}/p{01..12}     — 48 fixed-size pad records
    patterns/{a,b,c,d}/{NN}      — variable; one file per pattern
    scenes                        — 7 + 6×N bytes
    settings                      — 222 bytes
    sounds/{NNN}.wav              — bundled samples (slot → wav)

The ZIP additionally carries:

    /meta.json                    — teenage engineering pak metadata
    /projects/P{0X}.tar           — the inner project TAR (one of P01..P09)

**Critical:** every ZIP entry name MUST start with ``/`` or the device
displays "PAK FILE IS EMPTY" when you try to load the file.

Reference template
------------------

The writer needs a reference ``.ppak`` to extract the 222-byte
``settings`` template (we patch only BPM) and per-pad 27-byte templates
(we patch only sample_slot, time-stretch mode/bars/bpm, play_mode).
Pads/patterns/scenes/sounds are AUTHORED FRESH; everything else
preserved.

For tests, :func:`build_synthetic_template_ppak` produces a minimal
zero-filled template suitable as the ``reference_template_path``.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .song_format import (
    PAD_RECORD_SIZE,
    SETTINGS_SIZE,
    PpakSpec,
    build_pad,
    build_pattern,
    build_scenes,
    build_settings,
    pad_filename,
    pattern_filename,
)

# ----- Constants -------------------------------------------------------------

GROUPS = ("a", "b", "c", "d")
META_DEFAULTS: dict = {
    "info": "teenage engineering - pak file",
    "pak_version": 1,
    "pak_type": "user",
    "pak_release": "1.2.0",
    "device_name": "EP-133",
    "device_sku": "TE032AS001",
    "device_version": "2.0.5",
    "author": "stemforge",
    "base_sku": "TE032AS001",
}

# ZIP entries on a real .ppak start with "/"; missing this → device shows
# "PAK FILE IS EMPTY". Some captured templates use either form, so we
# normalise on read by stripping the leading slash before comparing.
_PROJECT_TAR_RE = re.compile(r"^/?projects/P([0-9]{2})\.tar$")
_META_NAMES = ("/meta.json", "meta.json")


# ----- Reference-template loader --------------------------------------------

class _ReferenceTemplate:
    """Cached unpack of a reference ``.ppak`` file.

    We extract:
    - ``meta.json``                  → dict (we patch ``generated_at``,
                                       ``author`` and ``device_sku`` from spec).
    - ``settings`` from the inner TAR → 222 bytes (preserve, patch BPM).
    - per-pad bytes for each (group, pad) → 27 bytes (preserve, patch
                                                       known fields).

    Anything else (existing patterns, scenes, sounds in the template)
    is ignored — :func:`build_ppak` authors fresh ones.
    """

    def __init__(
        self,
        meta: dict,
        settings: bytes,
        pad_templates: dict[tuple[str, int], bytes],
    ) -> None:
        self.meta = meta
        self.settings = settings
        self.pad_templates = pad_templates

    @classmethod
    def load(cls, ppak_path: Path) -> "_ReferenceTemplate":
        ppak_path = Path(ppak_path)
        if not ppak_path.is_file():
            raise FileNotFoundError(f"reference .ppak not found: {ppak_path}")

        meta: dict | None = None
        tar_bytes: bytes | None = None

        with zipfile.ZipFile(ppak_path, "r") as zf:
            names = zf.namelist()
            for name in names:
                if meta is None and name.lstrip("/") == "meta.json":
                    meta = json.loads(zf.read(name).decode("utf-8"))
                m = _PROJECT_TAR_RE.match(name)
                if m and tar_bytes is None:
                    tar_bytes = zf.read(name)

        if meta is None:
            raise ValueError(
                f"reference .ppak missing meta.json: {ppak_path} (entries={names})"
            )
        if tar_bytes is None:
            raise ValueError(
                f"reference .ppak missing /projects/PXX.tar: {ppak_path} (entries={names})"
            )

        settings: bytes | None = None
        pad_templates: dict[tuple[str, int], bytes] = {}

        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                # TAR member names may be stored with or without a leading "./"
                member_name = member.name.lstrip("./").lstrip("/")
                if member_name == "settings":
                    f = tf.extractfile(member)
                    if f is not None:
                        settings = f.read()
                    continue
                # pads/{group}/p{NN}
                parts = member_name.split("/")
                if len(parts) == 3 and parts[0] == "pads" and parts[1] in GROUPS:
                    pad_match = re.match(r"^p([0-9]{2})$", parts[2])
                    if pad_match:
                        pad_num = int(pad_match.group(1))
                        f = tf.extractfile(member)
                        if f is not None:
                            pad_templates[(parts[1], pad_num)] = f.read()

        if settings is None:
            raise ValueError(
                f"reference .ppak inner TAR is missing 'settings': {ppak_path}"
            )
        if len(settings) != SETTINGS_SIZE:
            raise ValueError(
                f"reference .ppak settings is {len(settings)} bytes, "
                f"expected {SETTINGS_SIZE}"
            )
        # Validate any pad templates we did find
        for key, blob in pad_templates.items():
            if len(blob) != PAD_RECORD_SIZE:
                raise ValueError(
                    f"reference .ppak pad {key!r} is {len(blob)} bytes, "
                    f"expected {PAD_RECORD_SIZE}"
                )

        return cls(meta=meta, settings=settings, pad_templates=pad_templates)


# ----- Synthesizer for tests + standalone builds ----------------------------

def build_synthetic_template_ppak(out_path: Path, *, project_slot: int = 1) -> Path:
    """Write a minimal zero-filled reference ``.ppak`` to ``out_path``.

    Useful for unit tests and for users who don't yet have a real device
    capture. The output contains:

    - ``/meta.json`` with default fields
    - ``/projects/PXX.tar`` containing 48 zero-filled 27-byte pad files
      and a 222-byte zero-filled ``settings`` file

    No patterns, scenes, or sounds — :func:`build_ppak` authors those.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the inner TAR
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        # 48 zero pad files
        for group in GROUPS:
            for pad in range(1, 13):
                _add_tar_bytes(tf, pad_filename(group, pad), bytes(PAD_RECORD_SIZE))
        # zero settings
        _add_tar_bytes(tf, "settings", bytes(SETTINGS_SIZE))

    tar_data = tar_buf.getvalue()
    meta = dict(META_DEFAULTS)
    meta["generated_at"] = _utc_iso8601()

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _zip_write_with_leading_slash(zf, "meta.json", json.dumps(meta, indent=2).encode("utf-8"))
        _zip_write_with_leading_slash(
            zf,
            f"projects/P{project_slot:02d}.tar",
            tar_data,
        )

    return out_path


# ----- Public entry point ----------------------------------------------------

def build_ppak(
    spec: PpakSpec,
    reference_template_path: Path,
    *,
    out_path: Path | None = None,
    author: str | None = None,
    device_sku: str | None = None,
) -> bytes:
    """Build a complete ``.ppak`` from ``spec`` + a reference template.

    Args:
        spec: the project to build.
        reference_template_path: path to a reference ``.ppak`` we extract
            ``settings`` and per-pad templates from. Use
            :func:`build_synthetic_template_ppak` to make one for tests.
        out_path: if given, write the bytes to this path before returning.
        author / device_sku: override ``meta.json`` defaults.

    Returns:
        The full ``.ppak`` byte contents.
    """
    _validate_spec(spec)
    template = _ReferenceTemplate.load(reference_template_path)

    # Build the inner TAR (POSIX format, no compression).
    tar_data = _build_inner_tar(spec, template)

    # Build meta.json — preserve template fields, patch generated_at + author.
    meta = dict(template.meta)
    meta.setdefault("info", META_DEFAULTS["info"])
    meta.setdefault("pak_version", META_DEFAULTS["pak_version"])
    meta.setdefault("pak_type", META_DEFAULTS["pak_type"])
    meta.setdefault("pak_release", META_DEFAULTS["pak_release"])
    meta.setdefault("device_name", META_DEFAULTS["device_name"])
    meta.setdefault("device_version", META_DEFAULTS["device_version"])
    meta["generated_at"] = _utc_iso8601()
    if author is not None:
        meta["author"] = author
    else:
        meta.setdefault("author", META_DEFAULTS["author"])
    if device_sku is not None:
        meta["device_sku"] = device_sku
        meta["base_sku"] = device_sku
    else:
        meta.setdefault("device_sku", META_DEFAULTS["device_sku"])
        meta.setdefault("base_sku", META_DEFAULTS["base_sku"])

    # Build the outer ZIP — every entry MUST have a leading slash.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _zip_write_with_leading_slash(zf, "meta.json", json.dumps(meta, indent=2).encode("utf-8"))
        _zip_write_with_leading_slash(
            zf, f"projects/P{spec.project_slot:02d}.tar", tar_data
        )
        # Bundle samples
        for slot, wav_path in sorted(spec.sounds.items()):
            wav_path = Path(wav_path)
            if not wav_path.is_file():
                raise FileNotFoundError(
                    f"sample slot {slot} wav missing: {wav_path}"
                )
            _zip_write_with_leading_slash(
                zf,
                f"sounds/{slot:03d}.wav",
                wav_path.read_bytes(),
            )

    data = buf.getvalue()
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
    return data


# ----- Internal helpers ------------------------------------------------------

def _validate_spec(spec: PpakSpec) -> None:
    if not (1 <= spec.project_slot <= 9):
        raise ValueError(f"project_slot must be 1..9, got {spec.project_slot}")
    if spec.bpm <= 0:
        raise ValueError(f"bpm must be positive, got {spec.bpm}")

    # Pattern uniqueness (group, index)
    seen_patterns: set[tuple[str, int]] = set()
    for p in spec.patterns:
        if p.group not in GROUPS:
            raise ValueError(f"pattern.group must be a|b|c|d, got {p.group!r}")
        key = (p.group, p.index)
        if key in seen_patterns:
            raise ValueError(f"duplicate pattern: {key}")
        seen_patterns.add(key)

    # Pad uniqueness (group, pad)
    seen_pads: set[tuple[str, int]] = set()
    for pd in spec.pads:
        if pd.group not in GROUPS:
            raise ValueError(f"pad.group must be a|b|c|d, got {pd.group!r}")
        key = (pd.group, pd.pad)
        if key in seen_pads:
            raise ValueError(f"duplicate pad: {key}")
        seen_pads.add(key)

    # Scene pattern indices must reference defined patterns (or 0 = silent).
    for i, sc in enumerate(spec.scenes):
        for group, idx in (("a", sc.a), ("b", sc.b), ("c", sc.c), ("d", sc.d)):
            if idx == 0:
                continue
            if (group, idx) not in seen_patterns:
                raise ValueError(
                    f"scene {i + 1} references undefined pattern {group}{idx:02d}"
                )


def _build_inner_tar(spec: PpakSpec, template: _ReferenceTemplate) -> bytes:
    """Build the inner ``project.tar`` (POSIX format, no compression)."""
    # Resolve pad specs by (group, pad)
    pad_by_key = {(pd.group, pd.pad): pd for pd in spec.pads}

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        # 48 pad files — required to be present
        for group in GROUPS:
            for pad in range(1, 13):
                pd = pad_by_key.get((group, pad))
                tmpl = template.pad_templates.get(
                    (group, pad), bytes(PAD_RECORD_SIZE)
                )
                if pd is None:
                    # Unassigned pad — use template as-is.
                    blob = tmpl
                else:
                    blob = build_pad(
                        sample_slot=pd.sample_slot,
                        play_mode=pd.play_mode,
                        time_stretch_bars=pd.time_stretch_bars,
                        template=tmpl,
                        project_bpm=spec.bpm,
                    )
                _add_tar_bytes(tf, pad_filename(group, pad), blob)

        # Patterns
        for p in spec.patterns:
            blob = build_pattern(p.events, p.bars)
            _add_tar_bytes(tf, pattern_filename(p.group, p.index), blob)

        # Scenes
        scenes_blob = build_scenes(spec.scenes, spec.time_sig)
        _add_tar_bytes(tf, "scenes", scenes_blob)

        # Settings — patch BPM into preserved template
        settings_blob = build_settings(spec.bpm, template.settings)
        _add_tar_bytes(tf, "settings", settings_blob)

    return buf.getvalue()


def _add_tar_bytes(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add ``data`` as ``name`` to ``tf`` with a stable, deterministic header."""
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0  # deterministic — easier to diff
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    tf.addfile(info, io.BytesIO(data))


def _zip_write_with_leading_slash(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    """Write a ZIP entry with a leading ``/`` (device requirement)."""
    if name.startswith("/"):
        entry_name = name
    else:
        entry_name = "/" + name
    info = zipfile.ZipInfo(entry_name)
    info.compress_type = zipfile.ZIP_DEFLATED
    # Deterministic mtime (matches our tar)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    zf.writestr(info, data)


def _utc_iso8601() -> str:
    """ISO-8601 UTC string with millisecond precision (matches TE format)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


