# Launchpad Pro Setup for StemForge

Manual Ableton configuration for the Launchpad MVP (64 pads = 4 stems x 16 bars).

## Prerequisites

- Novation Launchpad Pro connected via USB
- Ableton Live 12 with StemForge device installed
- At least one song processed through StemForge (curated manifest exists)

## Step 1: Enable Launchpad as Control Surface

1. Open **Preferences** > **Link, Tempo & MIDI**
2. Under **Control Surface**, add **Launchpad Pro**
3. Set **Input** and **Output** to the Launchpad's MIDI ports
4. Close Preferences

## Step 2: Session View Layout

StemForge creates 4 audio tracks when loading curated bars:

| Track | Stem | Color | Launchpad Column |
|-------|------|-------|-----------------|
| `[SF] Drums Bars` | drums | Red | 1 |
| `[SF] Bass Bars` | bass | Blue | 2 |
| `[SF] Vocals Bars` | vocals | Orange | 3 |
| `[SF] Other Bars` | other | Green | 4 |

Each track has 16 clip slots (one curated bar per slot).

## Step 3: Clip Launch Mapping

The Launchpad Pro in **Session mode** (default) auto-maps to Ableton's session
grid. Each pad triggers the clip at the corresponding track/slot intersection.

- **Columns 1-4**: StemForge stem tracks
- **Rows 1-8**: First 8 bars (visible page)
- **Arrow buttons**: Page down to see bars 9-16

## Step 4: Playing

- Press any pad to launch that bar from that stem
- Press pads in the same row to play matching bars across stems (they come from
  the same position in the song)
- Use the Scene Launch buttons (right column) to trigger all 4 stems at once
  for a given bar

## Step 5: Save as Template (Optional)

1. **File** > **Save Live Set as Template...**
2. Name it `StemForge Launchpad`
3. Future sessions start with the Launchpad pre-configured

## Warp Modes

StemForge sets warp modes automatically:
- **Drums/Bass**: Beats mode (preserves transients)
- **Vocals/Other**: Complex mode (preserves pitch/timbre)

## Troubleshooting

- **No pads light up**: Ensure Launchpad is in Session mode (press Session button)
- **Clips don't play**: Check track monitoring is set to "Auto" or "In"
- **Wrong tempo**: StemForge sets tempo from the manifest BPM automatically
- **Missing bars**: If a stem has fewer than 16 bars, the missing clip slots
  will be empty (this happens when vocals end before drums)
