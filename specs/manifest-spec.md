Schema (pydantic)

# stemforge/manifest_schema.py  (canonical; ep133-ppak mirrors this)
from pydantic import BaseModel, Field
from typing import Literal

PadLabel  = Literal["7","8","9","4","5","6","1","2","3",".","0","ENTER"]
Group     = Literal["A","B","C","D"]
TimeMode  = Literal["off","bar","bpm"]
PlayMode  = Literal["oneshot","key","legato"]
Stem      = Literal["drums","bass","vocals","other","full"]


class SampleMeta(BaseModel):
    """Per-sample metadata.

    Used as both:
      - per-file sidecar:  .manifest_<hash>.json  (next to the .wav)
      - batch entry:       inside BatchManifest.samples
    """
    # Identity
    file:        str | None = None   # filename relative to manifest dir; required in batch
    audio_hash:  str | None = None   # sha256 of audio bytes, first 16 hex chars

    # Display
    name:        str | None = None   # device display name (≤16 chars); defaults to file stem

    # Tempo / timing
    bpm:         float | None = None
    time_mode:   TimeMode | None = None   # implicit "bpm" if bpm is set
    bars:        float | None = None      # source length, informational

    # Playback
    playmode:    PlayMode | None = None

    # Provenance (informational)
    source_track: str | None = None
    stem:         Stem | None = None
    role:         str | None = None       # "loop", "kick", "snare", "one_shot", free-form

    # Advisory placement hints (loader uses ONLY if no CLI override)
    suggested_group: Group    | None = None
    suggested_pad:   PadLabel | None = None


class BatchManifest(BaseModel):
    """Directory-level manifest. Filename: .manifest.json in root of consumed dir."""
    version: int = 1
    track:   str | None = None
    bpm:     float | None = None      # default for entries that omit it
    samples: list[SampleMeta] = Field(default_factory=list)
Hash convention
<hash> in .manifest_<hash>.json = sha256 of the WAV file's raw bytes, lowercase hex, first 16 chars. Example: .manifest_a3f2b4c5d6e7f8a9.json. Short enough to be human-readable, collision-safe for any realistic library.

Resolution order in the loader
CLI flags (highest)
Sidecar .manifest_<hash>.json next to the WAV
Batch .manifest.json in the WAV's directory (entry matched by audio_hash or file)
Built-in defaults (lowest: --project 1 --group A, slot from cursor, etc.)
CLI always wins. Manifest is purely a default-source.

Message to paste into the StemForge session

I'm building an EP-133 loader skill in ep133-ppak. To make sample loading
zero-friction, I need StemForge to drop a small JSON sidecar next to every
exported audio file (and optionally a batch manifest in the root).

Pydantic schema (canonical — please put this in `stemforge/manifest_schema.py`):

```python
from pydantic import BaseModel, Field
from typing import Literal

PadLabel  = Literal["7","8","9","4","5","6","1","2","3",".","0","ENTER"]
Group     = Literal["A","B","C","D"]
TimeMode  = Literal["off","bar","bpm"]
PlayMode  = Literal["oneshot","key","legato"]
Stem      = Literal["drums","bass","vocals","other","full"]


class SampleMeta(BaseModel):
    file:        str | None = None
    audio_hash:  str | None = None
    name:        str | None = None
    bpm:         float | None = None
    time_mode:   TimeMode | None = None
    bars:        float | None = None
    playmode:    PlayMode | None = None
    source_track: str | None = None
    stem:         Stem | None = None
    role:         str | None = None
    suggested_group: Group    | None = None
    suggested_pad:   PadLabel | None = None


class BatchManifest(BaseModel):
    version: int = 1
    track:   str | None = None
    bpm:     float | None = None
    samples: list[SampleMeta] = Field(default_factory=list)
```

Two write modes:

1. **Per-file sidecar**: for every exported `<name>.wav`, also write
   `.manifest_<hash>.json` in the SAME directory, where `<hash>` is the
   sha256 of the wav bytes, lowercase hex, first 16 chars. The file
   contains a single `SampleMeta` object (audio_hash + file optional
   in this form, but nice to include).

2. **Batch manifest**: in the root of any directory you export, write
   `.manifest.json` containing a `BatchManifest` with one `SampleMeta`
   per file. Each entry MUST set `file`, SHOULD set `audio_hash`.

Both can coexist. ep133-ppak's loader will check sidecar first, then
batch, then fall back to defaults. CLI flags always win.

Field-population guidance:
- `name`: 16-char-trimmed display string (drop extension, replace `_`
  with space if cleaner). The device shows this in the sample browser.
- `bpm`: the *source* BPM of the loop. Required for time-stretchable loops.
- `time_mode`: omit unless you specifically want to override "bpm-when-bpm-set".
- `playmode`: `"oneshot"` for one-shots / drum hits, `"key"` for sustained
  tonal samples, `"legato"` rare. Default to `"oneshot"` for sliced drums,
  `"key"` for melodic full-stem loops.
- `stem` / `role`: free metadata — used for routing and display, not loading.
- `suggested_group` / `suggested_pad`: only set when you have a strong
  opinion (e.g., drums → group A). The user's CLI args override these.

This schema does NOT replace `stems.json` — that stays as the
pipeline-level manifest. This is a sample-level sidecar for hardware
loaders.
