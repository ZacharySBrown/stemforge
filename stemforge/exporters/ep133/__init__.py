"""
EP-133 K.O. II package.

Existing modules:
- ``EP133Exporter`` — formats stems/slices for EP-133 (Session-mode workflow).
- ``EP133Client``   — SysEx uploader over USB-MIDI. See PORT_MAP.md.

Song-mode export pipeline (arrangement → ``.ppak``):
- ``song_format`` (Track A): ``PpakSpec``, ``Pattern``, ``SceneSpec``, ``PadSpec``,
  ``Event`` dataclasses describing a song-mode project.
- ``ppak_writer`` (Track A): ``build_ppak(spec, reference_template)`` byte builder.
- ``song_resolver`` (Track C): ``resolve_scenes(arrangement, manifest)`` →
  list of per-locator ``Snapshot``s.
- ``song_synthesizer`` (Track C): ``synthesize(snapshots, manifest, ...)`` →
  ``PpakSpec`` ready for the writer.

Example:
    from stemforge.exporters.ep133 import EP133Client
    with EP133Client.open() as client:
        client.upload_sample(Path("kick.wav"), slot=1)
"""

from .exporter import EP133Exporter  # noqa: F401


def __getattr__(name):
    # Lazy-load EP133Client so importing the package for `EP133Exporter`
    # doesn't pull in mido + the hardware-facing layers.
    if name == "EP133Client":
        from .client import EP133Client
        return EP133Client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
