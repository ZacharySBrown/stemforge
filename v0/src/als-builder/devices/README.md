# Device XML fragments

Each file is a minimal `<DeviceChain>`-compatible device node that can be
inserted into a Live 12 AudioTrack or MidiTrack.

**Conventions:**

- Every element's `Id` attribute is `"0"` — `builder.py` rewrites all IDs
  to be set-wide unique during assembly.
- Parameter values are stored in `<X><Manual Value="…"/></X>` form, matching
  Live 12's on-disk layout.
- Only the parameter fields we actively manipulate from `tracks.yaml` are
  populated. Everything else inherits Live's defaults when the set is opened
  (Live fills in missing child elements on first save).
- Stock devices only. VST3 plugins are emitted from `vst3_lookup.yaml` at
  build time via a separate code path.

**To extend:** copy the `Compressor.xml` shape, then save a real Live 12 set
containing the device, gunzip it, find the `<DeviceName>` node, and adapt.

Device-parameter mapping for `tracks.yaml`:

| Device | YAML key | XPath into fragment |
|---|---|---|
| Compressor | `threshold_db` | `Compressor/Threshold/Manual/@Value` |
| Compressor | `ratio` | `Compressor/Ratio/Manual/@Value` |
| Compressor | `attack_ms` | `Compressor/Attack/Manual/@Value` |
| Compressor | `release_ms` | `Compressor/Release/Manual/@Value` |
| EQ Eight | (none for v0) | n/a — flat default |
| Reverb | `decay_sec` | `Reverb/DecayTime/Manual/@Value` (ms internally, convert × 1000) |
| Reverb | `diffusion` | `Reverb/Diffusion/Manual/@Value` |
| Utility | `gain_db` | `Utility/Gain/Manual/@Value` |
| Simpler | `mode`, `warp` | `OriginalSimpler/Playback/PlayMode/Manual/@Value` (0=Classic, 1=One-Shot, 2=Slice), `OriginalSimpler/Player/Warping/Manual/@Value` (true/false) |
