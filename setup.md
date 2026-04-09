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
