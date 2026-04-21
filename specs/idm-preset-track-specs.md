

## 10. `pipelines/default.yaml`

This is the user-editable pipeline configuration. The M4L device reads this
file to know which template track to duplicate per stem type, and what effect
parameter values to dial in. Claude Code writes this file with sensible IDM
defaults. The user edits it over time to build their own signal chain presets.

```yaml
# pipelines/default.yaml
# ─────────────────────────────────────────────────────────────────────────────
# StemForge Pipeline Configuration
# Edit this file to customize how stems are processed in Ableton.
#
# Each pipeline is a named set of stem→template mappings.
# When stemforge split runs with --pipeline <name>, that name is baked into
# stems.json and the M4L device uses it to select the right mappings.
#
# Template tracks must exist in your Ableton "StemForge Templates" set.
# See setup.md for how to build them.
#
# Effect parameter indices: use the M4L device's "Inspect" button to find
# the parameter index for any device on any track. VSTs expose their
# parameters by index just like native devices.
#
# Warp modes: beats=0, tones=1, texture=2, re-pitch=3, complex=4, complex-pro=5
# ─────────────────────────────────────────────────────────────────────────────

pipelines:

  # ── DEFAULT: clean stems, minimal processing ────────────────────────────────
  default:
    description: "Clean stems, warped and looped, ready to use"
    stems:
      drums:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true
      drum:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true
      bass:
        template: "SF | Bass"
        color: 0x0055FF
        warp_mode: beats
        loop: true
      other:
        template: "SF | Texture"
        color: 0x00AA44
        warp_mode: complex
        loop: true
      vocals:
        template: "SF | Vocals"
        color: 0xFF8800
        warp_mode: tones
        loop: true
      synthesizer:
        template: "SF | Texture"
        color: 0xAA00FF
        warp_mode: complex
        loop: true
      guitar:
        template: "SF | Texture"
        color: 0xFFCC00
        warp_mode: complex
        loop: true
      electricguitar:
        template: "SF | Texture"
        color: 0xFFCC00
        warp_mode: complex
        loop: true
      piano:
        template: "SF | Texture"
        color: 0xAA00FF
        warp_mode: tones
        loop: true

  # ── IDM CRUSHED: heavy degradation — Aphex/Squarepusher territory ────────────
  idm_crushed:
    description: "Bitcrushed, saturated, degraded — maximum texture"
    stems:
      drums:
        template: "SF | Drums Crushed"
        color: 0xFF2400
        warp_mode: beats
        loop: true
        effects:
          # Device 0: LO-FI-AF (VST)
          # Digital section — bitcrusher at ~10-bit, sample rate heavy reduction
          - device: 0
            params:
              # param indices must be verified via M4L inspect on your machine
              # these are approximate starting points for LO-FI-AF
              Digital_Bits: 0.55        # ~10-bit range (0=16bit, 1=4bit)
              Digital_Rate: 0.45        # sample rate reduction
              Analog_Flux: 0.25         # tape warble
              Global_Strength: 0.75     # overall intensity
          # Device 1: Decapitator (VST)
          - device: 1
            params:
              Drive: 0.35
              Style: 0.0                # style A = Ampex 350 warmth
              Mix: 0.6
          # Device 2: Ableton Compressor
          - device: 2
            params:
              Ratio: 0.85               # ~8:1
              Attack_Time: 0.05
              Release_Time: 0.25
              Makeup: 0.55

      drum:
        template: "SF | Drums Crushed"
        color: 0xFF2400
        warp_mode: beats
        loop: true
        effects:
          - device: 0
            params:
              Digital_Bits: 0.55
              Digital_Rate: 0.45
              Analog_Flux: 0.25
              Global_Strength: 0.75
          - device: 1
            params:
              Drive: 0.35
              Style: 0.0
              Mix: 0.6

      bass:
        template: "SF | Bass"
        color: 0x0055FF
        warp_mode: beats
        loop: true
        effects:
          # Device 0: Ableton EQ Eight (highpass + low shelf)
          - device: 0
            params:
              "1 Frequency": 0.22       # highpass ~40Hz
              "2 Gain": 0.55            # low shelf boost ~80Hz
          # Device 1: LO-FI-AF — analog section only, subtle tape
          - device: 1
            params:
              Analog_Flux: 0.15
              Analog_Press: 0.3
              Global_Strength: 0.35     # subtle on bass

      other:
        template: "SF | Texture Verb"
        color: 0x00AA44
        warp_mode: complex
        loop: true
        effects:
          # Device 0: LO-FI-AF — spectral + analog for texture weirdness
          - device: 0
            params:
              Spectral_Ripple: 0.3
              Spectral_MP3: 0.2
              Analog_Flux: 0.4
              Global_Strength: 0.55
          # Device 1: EchoBoy (VST) — tape echo
          - device: 1
            params:
              Style: 0.3                # tape echo style
              Time: 0.5                 # 1/4 note synced
              Feedback: 0.3
              Mix: 0.35
          # Device 2: Ableton Reverb — large hall
          - device: 2
            params:
              Room_Size: 0.75
              Decay_Time: 0.7
              Dry_Wet: 0.35

      synthesizer:
        template: "SF | Texture Verb"
        color: 0xAA00FF
        warp_mode: complex
        loop: true
        effects:
          - device: 0
            params:
              Spectral_Ripple: 0.4
              Spectral_MP3: 0.3
              Global_Strength: 0.6

  # ── GLITCH: Crystallizer + spectral destruction ────────────────────────────
  glitch:
    description: "Granular reverse textures, spectral mangling — Four Tet / Boards of Canada"
    stems:
      drums:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true

      drum:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true

      bass:
        template: "SF | Bass"
        color: 0x0055FF
        warp_mode: beats
        loop: true

      other:
        template: "SF | Texture Crystallized"
        color: 0x00AA44
        warp_mode: complex-pro
        loop: true
        effects:
          # Device 0: Crystallizer (VST) — granular reverse echo
          - device: 0
            params:
              Pitch: 0.43               # -7 semitones (0=+12, 0.5=0, 1=-12)
              Splice: 0.2               # short grain size
              Delay: 0.4                # delay time
              Recycle: 0.35             # feedback
              Reverse: 1.0              # reverse on
              Mix: 0.7
          # Device 1: Ableton Reverb — wash it out
          - device: 1
            params:
              Room_Size: 0.9
              Decay_Time: 0.85
              Dry_Wet: 0.6

      synthesizer:
        template: "SF | Texture Crystallized"
        color: 0xAA00FF
        warp_mode: complex-pro
        loop: true
        effects:
          - device: 0
            params:
              Pitch: 0.57               # +7 semitones
              Splice: 0.3
              Recycle: 0.45
              Reverse: 1.0
              Mix: 0.65

  # ── AMBIENT: long tails, wide spaces — slow IDM / textural ─────────────────
  ambient:
    description: "Expansive reverbs, slow modulation — textural/ambient IDM"
    stems:
      drums:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true
        effects:
          # LO-FI-AF — very subtle analog warmth only
          - device: 0
            params:
              Analog_Flux: 0.1
              Global_Strength: 0.2

      drum:
        template: "SF | Drums Raw"
        color: 0xFF2400
        warp_mode: beats
        loop: true

      bass:
        template: "SF | Bass"
        color: 0x0055FF
        warp_mode: tones
        loop: true

      other:
        template: "SF | Texture Verb"
        color: 0x00AA44
        warp_mode: complex-pro
        loop: true
        effects:
          # PhaseMistress — slow deep phase
          - device: 0
            params:
              Rate: 0.08                # very slow
              Depth: 0.8
              Style: 0.0
          # EchoBoy — long tape delay
          - device: 1
            params:
              Style: 0.3
              Time: 0.75               # dotted 1/4
              Feedback: 0.45
              Mix: 0.45
          # SuperPlate/Little Plate — big plate reverb
          - device: 2
            params:
              Decay: 0.85
              Mix: 0.5

      synthesizer:
        template: "SF | Texture Verb"
        color: 0xAA00FF
        warp_mode: complex-pro
        loop: true
```

---

## 11. Ableton Template Tracks — Manual Setup Instructions

**Claude Code must write `setup.md` with these exact instructions.**
These template tracks are built by hand once in Ableton — they cannot be
created programmatically. The M4L device duplicates them.

```markdown
## Building the StemForge Template Set

### Step 1: Create a dedicated Ableton set
- File → New Live Set
- Save as: ~/Music/Ableton/Projects/StemForge Templates/StemForge Templates.als
- This set stays open while you produce. Never delete it.

### Step 2: Add ~/stemforge/processed to Ableton browser
Browser → Places → right-click → "Add Folder" → select ~/stemforge/processed
New stems appear here instantly after each stemforge run.

### Step 3: Build these template tracks (in order)
Each track below is a recipe. Build exactly this — the M4L device finds them
by name. Track names must match exactly.

─────────────────────────────────────────────────────────────────────────
TRACK 1: "SF | Drums Raw"   [Audio Track]   Color: Red
─────────────────────────────────────────────────────────────────────────
Devices (left to right on the track):
  1. Ableton Compressor
     - Ratio: 2.5:1
     - Attack: 10ms
     - Release: 80ms
     - Makeup: 0dB
  2. Ableton EQ Eight
     - Band 1: High shelf +2dB @ 10kHz

Clip settings (when audio is loaded by M4L):
  - Warp: ON, Mode: Beats
  - Loop: ON
  - Launch Mode: Toggle

─────────────────────────────────────────────────────────────────────────
TRACK 2: "SF | Drums Crushed"   [Audio Track]   Color: Red (darker)
─────────────────────────────────────────────────────────────────────────
Devices:
  1. LO-FI-AF (VST3 — Unfiltered Audio)
     Default preset: "Default"
     Sections active: Digital ON, Analog ON, Spectral OFF, Convolution OFF
     - Digital: Bits ~10-bit, Rate moderate
     - Analog: Flux (tape warble) moderate
     - Global Strength: 0.7
  2. Decapitator (VST3 — Soundtoys)
     - Style: A (Ampex 350)
     - Drive: 3
     - Mix: 60%
  3. Ableton Compressor
     - Ratio: 6:1
     - Attack: 5ms
     - Release: 60ms
     - Makeup: +2dB
  4. EchoBoy Jr (VST3 — Soundtoys)  [optional, can bypass]
     - Style: Tape Echo
     - Time: Sync 1/16
     - Feedback: 15%
     - Mix: 12%

─────────────────────────────────────────────────────────────────────────
TRACK 3: "SF | Bass"   [Audio Track]   Color: Blue
─────────────────────────────────────────────────────────────────────────
Devices:
  1. Ableton EQ Eight
     - Band 1: High Pass @ 35Hz
     - Band 2: Low shelf +2dB @ 80Hz
     - Band 3: High shelf -1dB @ 8kHz
  2. Ableton Compressor
     - Ratio: 4:1
     - Attack: 20ms
     - Release: 120ms
  3. LO-FI-AF (VST3)
     Sections: Analog ON only
     - Analog: Flux minimal (0.1), Press moderate (0.3)
     - Global Strength: 0.3
  4. Decapitator (VST3)
     - Style: E (warm transformer)
     - Drive: 1.5
     - Low Cut: 40Hz
     - Mix: 40%

─────────────────────────────────────────────────────────────────────────
TRACK 4: "SF | Texture Verb"   [Audio Track]   Color: Green
─────────────────────────────────────────────────────────────────────────
Devices:
  1. PhaseMistress (VST3 — Soundtoys)
     - Rate: slow (20%)
     - Depth: 60%
     - Style: Vintage
  2. EchoBoy (VST3 — Soundtoys)
     - Style: Tape Echo
     - Time: Sync 1/4
     - Feedback: 35%
     - Saturation: 20%
     - Mix: 40%
  3. Ableton Reverb
     - Room Size: 75%
     - Decay: 3.0s
     - Diffusion: 90%
     - Dry/Wet: 35%
  4. LO-FI-AF (VST3)
     Sections: Spectral ON, Analog ON
     - Spectral: Ripple 0.2, MP3 0.15
     - Analog: Flux 0.3
     - Global Strength: 0.45

Clip settings: Warp Complex, Loop ON

─────────────────────────────────────────────────────────────────────────
TRACK 5: "SF | Texture Crystallized"   [Audio Track]   Color: Green (teal)
─────────────────────────────────────────────────────────────────────────
Devices:
  1. Crystallizer (VST3 — Soundtoys)
     - Pitch: -5 semitones
     - Splice: short
     - Delay: 40%
     - Recycle: 30%
     - Reverse: ON
     - Mix: 70%
  2. Ableton Reverb
     - Room Size: 90%
     - Decay: 5.0s
     - Dry/Wet: 60%
  3. Ableton Utility
     - Width: 130%

Clip settings: Warp Complex Pro, Loop ON

─────────────────────────────────────────────────────────────────────────
TRACK 6: "SF | Vocals"   [Audio Track]   Color: Orange
─────────────────────────────────────────────────────────────────────────
Devices:
  1. Ableton EQ Eight
     - Band 1: High Pass @ 120Hz
     - Band 2: Presence boost +2dB @ 3kHz
  2. Ableton Compressor
     - Ratio: 3:1
     - Attack: 15ms
     - Release: 100ms
  3. LO-FI-AF (VST3)
     Sections: Analog ON, Convolution ON (mic IRs for vintage feel)
     - Convolution: Amount 0.3, select "phone mic" or "vintage mic" IR
     - Analog: Flux 0.2, Press 0.25
     - Global Strength: 0.4
  4. EchoBoy (VST3 — Soundtoys)
     - Style: Space Echo
     - Time: Sync 1/8
     - Feedback: 20%
     - Mix: 25%

─────────────────────────────────────────────────────────────────────────
TRACK 7: "SF | Beat Chop Simpler"   [MIDI Track]   Color: Red (bright)
─────────────────────────────────────────────────────────────────────────
Instruments + Devices:
  1. Ableton Simpler
     - Mode: Classic (not Slice — Slice mode is manual)
     - Warp: ON, Complex Pro
     - Note: M4L loads beat WAV directly into Simpler's sample slot
  2. Decapitator (VST3 — Soundtoys)
     - Style: B
     - Drive: 2
     - Mix: 50%
  3. PrimalTap (VST3 — Soundtoys)
     - Clock: ~100ms
     - Feedback: 20%
     - Mix: 20%

Note: For this track, M4L loads the DRUMS beat slice (beat_001.wav or most
energetic beat as determined by RMS ranking) into Simpler's sample slot.
The M4L device targets Simpler's "Sample" parameter via LOM.

### Step 4: Group all tracks
Select all 7 tracks → Cmd+G → name group "StemForge Templates" → color grey.
Fold the group. These tracks stay in the set forever.

### Step 5: Install AbletonOSC (optional, for tempo sync from CLI)
git clone https://github.com/ideoforms/AbletonOSC /tmp/AbletonOSC
cp -r /tmp/AbletonOSC/AbletonOSC \
  ~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonOSC
Then: Live Preferences → MIDI → Control Surface → AbletonOSC

### Step 6: Install the StemForge Loader M4L device
Drag StemForgeLoader.amxd from the stemforge/m4l/ folder onto any track
in the StemForge Templates set (a dedicated MIDI track called "SF Loader"
is ideal). It will stay there permanently.
```

