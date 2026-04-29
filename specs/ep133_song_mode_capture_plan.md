# EP-133 Song Mode — Capture Plan

Goal: get enough captured `.ppak` baselines from a device with song
mode configured to reverse-engineer where the **song-position list** is
stored. This unblocks song-mode support in `stemforge`'s EP-133 exporter
and resolves the unexplained non-zero bytes phones24 documented at
scenes-trailer offsets 601-603.

## Background

Song mode is **not** automatic chaining of committed scenes. It's a
separate, explicit on-device setup:

- `SHIFT + MAIN` commits the current beat as a scene (creates the next
  scene as a duplicate). This is what populates the per-scene chunks at
  the head of the `scenes` file.
- `Hold MAIN + tap ENTER` opens the song-list editor — a separate
  ordered list of "song positions", each pointing to a scene. Up to 99
  positions; max song length 99 × 99 bars = 9,801 bars.

The song-position list is **not** in any byte map we have:
- `phones24/ep133-export-to-daw`'s `collectScenesSettings()` reads only
  `timeSignature` from the scenes file (bytes 11-12) and ignores
  everything else.
- `ZacharySBrown/ep133-ppak/PROTOCOL.md` covers pad-record bytes but
  not the scenes-file trailer.
- The phones24 spec's example trailer shows non-zero bytes at offsets
  601-603 (`127, 2, 8`) without naming them — likely song-mode state.

Most plausible storage location is **scenes bytes 605-711** (107
unused bytes in the trailer of every reference we've captured, more
than enough room for 99 single-byte scene references plus flags). A
new file inside the project TAR is a less-likely alternative.

## Setup

- EP-133 connected via USB-C
- Sample Tool (Chrome WebMIDI at
  `https://teenageengineering.com/apps/ep-sample-tool`) — only used for
  the **Backup** action; no edits via the tool itself
- Existing project with at least 3 committed scenes (the project that
  produced `docs/ep133-song-triage/reference_minimal.ppak` is ideal —
  rebuild on-device if it's no longer there)

## Captures to record

Save every `.ppak` to `docs/ep133-song-triage/song-mode-captures/`.
Filenames are matched verbatim by future analysis tools.

| # | File | Action |
|---|------|--------|
| 0 | `00_baseline_no_song.ppak` | **Reuse** existing `reference_minimal.ppak` if intact, OR re-Backup the same project before opening the song editor |
| 1 | `01_song_distinctive_sequence.ppak` | Hold MAIN + tap ENTER → enter sequence **3 → 1 → 2 → 1 → 3 → 1 → 2** (7 positions, easy to spot) → exit editor → Backup |
| 2 | `02_song_one_position_changed.ppak` | Edit position 7 from `2` → `3` → exit → Backup. Diff against #1 isolates a single-position byte from the song-mode-on flag |
| 3 (optional) | `03_song_cleared.ppak` | Clear the song (whatever the device's clear-song operation is — TBD; check song editor menu) → Backup. Verifies the "no song" state byte. |

Between captures #1 and #2 you may also want to test:

- Saving with the device on **scene 2** vs **scene 1** (no other
  changes). If bytes 601-603 vary, they encode "current scene
  position", not song state.
- Toggling between scene mode and song mode at save time — same
  reasoning.

If unsure, capture extra `.ppak`s liberally — they're 200KB each, and
extra data points only sharpen the diff.

## Expected analysis

```python
import zipfile, tarfile, io
from pathlib import Path

def extract_scenes(p):
    with zipfile.ZipFile(p) as zf:
        tar_b = zf.read(next(n for n in zf.namelist() if n.endswith('.tar')))
    with tarfile.open(fileobj=io.BytesIO(tar_b)) as tf:
        return tf.extractfile('scenes').read()

# Diff #0 vs #1: bytes that change reveal song-mode storage
# Diff #1 vs #2: bytes that change reveal a single song-position entry
# Diff #1 vs #3: bytes that change reveal the song-mode-active flag
```

Three outcomes are possible:

1. **All differences land in `scenes` bytes 605-711.** Cleanest case —
   we know the format from one diff session. Update
   `stemforge/exporters/ep133/song_format.py:build_scenes` to accept an
   optional song-position list and emit it into the trailer.
2. **A new file appears in the project TAR** (e.g. `song`,
   `song_positions`, etc). We learn its format by reading its bytes
   directly; trivially handled by the `.ppak` writer.
3. **Differences spread into other files** (e.g. `settings` — though
   our writer doesn't emit one — or per-pad records). Indicates
   song mode also touches state we hadn't expected; capture a few more
   small variations (positions 1→2 only) to narrow it down.

## After capture

Drop the `.ppak` files into `docs/ep133-song-triage/song-mode-captures/`
on `feat/ep133-song-export` (or another branch and let the writer
maintainer cherry-pick). Tell the next session what's there; they can
do the byte diff and update the writer in one short pass.

## What to avoid

- Don't push the user's audio in these `.ppak`s if the project contains
  copyrighted samples. The `reference_minimal.ppak` baseline is fine
  (drum hits only).
- Don't change samples, pads, patterns, or scene contents between
  captures — the only varying state should be song-mode setup.
- Don't trust the device's "current scene" indicator at save time
  unless explicitly documented; capture it consistently (always save
  with scene 1 active, for example) to rule it out as a confounder.
