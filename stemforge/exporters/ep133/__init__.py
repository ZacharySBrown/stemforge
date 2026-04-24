"""
EP-133 package. Contains:

- `EP133Exporter` — formats stems/slices for EP-133 (existing behavior).
- `EP133Client`   — SysEx uploader over USB-MIDI (new). See PORT_MAP.md.

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
