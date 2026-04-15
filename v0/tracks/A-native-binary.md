# Track A — Native Inference Binary

## Goal

Produce a signed, notarized, universal2 macOS binary `stemforge-native` that runs the StemForge pipeline with zero Python environment on the user's machine.

## v0 Approach: PyInstaller

Not ONNX. ONNX is v1. For v0 we freeze the existing working Python pipeline. Lower risk, proves the shipping pipeline.

## Inputs

- `stemforge/` package (existing source)
- `v0/interfaces/ndjson.schema.json` — the event contract binary must conform to
- Apple Developer ID Application certificate (injected via CI secrets)
- ffmpeg universal2 static binary (fetched from `https://evermeet.cx/ffmpeg/`)

## Outputs

- `v0/build/stemforge-native` — universal2 Mach-O binary, signed, notarized
- `v0/build/build-native.sh` — reproducible build script
- `v0/build/stemforge-native.spec` — PyInstaller spec file
- `v0/state/A/artifacts.json` — metadata (sha256, size, arch, signed, notarized)
- `v0/state/A/done.flag` — touched on success

## Subtasks

### A1 — Wire `--json-events` into CLI
Current state: the `forge` command emits NDJSON already (see `stemforge/cli.py:537`). The `split` command does not.

Add a single `--json-events` flag (global, or per-command) that:
- Silences Rich output entirely
- Emits NDJSON conforming to `v0/interfaces/ndjson.schema.json`
- Maps existing events: `started`, `progress (phase=splitting|slicing|writing_manifest)`, `stem` per stem, `bpm`, `slice_dir` per stem_beats/, `complete`, `error`

**File touched:** `stemforge/cli.py` only. Do not restructure other modules.

### A2 — ffmpeg bundling
Fetch universal2 static ffmpeg into `v0/build/vendor/ffmpeg`. PyInstaller's `--add-binary` flag includes it. At runtime, `ensure_wav()` in `cli.py` is updated to first check `sys._MEIPASS/ffmpeg` before `shutil.which("ffmpeg")`.

### A3 — Model weights policy
**Do NOT bundle weights into the binary.** Binary size would balloon past 2GB.

On first use, binary checks `~/Library/Application Support/StemForge/models/`. If missing, downloads `htdemucs` and `htdemucs_6s` checkpoints from Facebook AI's public URL, emits `progress phase=downloading_weights`. Cache keyed by model SHA.

### A4 — PyInstaller spec
```python
# v0/build/stemforge-native.spec
a = Analysis(
    ['../../stemforge/cli.py'],
    binaries=[('vendor/ffmpeg', '.')],
    datas=[('../../pipelines', 'pipelines')],
    hiddenimports=[
        'stemforge', 'stemforge.backends.demucs',
        'stemforge.backends.lalal', 'stemforge.backends.musicai',
        'torch', 'torchaudio', 'demucs', 'librosa', 'soundfile',
    ],
    hookspath=['hooks'],
    ...
)
# Collect-all torch/demucs/librosa via hook files for transitive deps.
exe = EXE(pyz, a.scripts, ..., name='stemforge-native',
          target_arch='universal2', codesign_identity=os.environ['CODESIGN_ID'],
          entitlements_file='entitlements.plist')
```

### A5 — Entitlements
Torch and numpy need JIT:
```xml
<key>com.apple.security.cs.allow-jit</key><true/>
<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
<key>com.apple.security.cs.disable-library-validation</key><true/>
```

### A6 — Universal2 strategy
PyInstaller cross-arch for torch is fragile. Build on each arch separately then `lipo -create` merge:
```bash
# On x86_64 runner:
pyinstaller stemforge-native.spec --target-arch x86_64
mv dist/stemforge-native dist/stemforge-native-x86_64
# On arm64 runner:
pyinstaller stemforge-native.spec --target-arch arm64
mv dist/stemforge-native dist/stemforge-native-arm64
# Later (either runner):
lipo -create dist/stemforge-native-x86_64 dist/stemforge-native-arm64 \
     -output v0/build/stemforge-native
```

This coordinates with Track F (CI uses two macos runners).

### A7 — Codesign + notarize
```bash
codesign --force --deep --options runtime \
  --entitlements entitlements.plist \
  --sign "$CODESIGN_ID" \
  v0/build/stemforge-native

ditto -c -k --keepParent v0/build/stemforge-native v0/build/stemforge-native.zip
xcrun notarytool submit v0/build/stemforge-native.zip \
  --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APP_PW" --wait
xcrun stapler staple v0/build/stemforge-native
```

### A8 — Self-test
Binary must pass:
```bash
./stemforge-native split tests/fixtures/short_loop.wav --json-events 2>/dev/null \
  | jq -c 'select(.event)' \
  | v0/tests/validate-ndjson.py
```
And produce `~/stemforge/processed/short_loop/stems.json` conforming to the existing manifest schema.

## Acceptance

- `file v0/build/stemforge-native` → "Mach-O universal binary with 2 architectures"
- `codesign -dvv v0/build/stemforge-native` → valid Developer ID signature
- `spctl -a -t exec v0/build/stemforge-native` → "accepted"
- `./stemforge-native --version` prints version and exits 0
- `./stemforge-native split test.wav --json-events` emits valid NDJSON per schema
- Runs on a freshly-imaged Mac with no Homebrew, no Python installed

## Risk / Unknowns

- PyInstaller + torch: known to need aggressive `--collect-all`. Budget iteration.
- Universal2 torch wheels: available on PyPI but not all versions. Pin to a torch release with confirmed universal2 wheel.
- Notarization latency: 5 min to 4 hours. CI must wait.
- Binary size estimate: 600MB – 1.2GB. Acceptable for v0.

## Subagent Brief

You are implementing Track A of StemForge v0.

**Read before starting:**
- `v0/PLAN.md`
- `v0/SHARED.md`
- `v0/interfaces/ndjson.schema.json`
- `v0/tracks/A-native-binary.md` (this file)
- `stemforge/cli.py` (understand the existing `forge` NDJSON emissions)

**Produce:**
- Changes to `stemforge/cli.py` (add `--json-events` flag, conforming to schema)
- `v0/build/build-native.sh` (reproducible build script)
- `v0/build/stemforge-native.spec` (PyInstaller spec)
- `v0/build/entitlements.plist`
- `v0/build/hooks/` (PyInstaller hooks for torch/demucs/librosa if needed)
- `v0/build/stemforge-native` (the binary — on CI only; local dev may skip signing)
- `v0/state/A/progress.ndjson` (append status updates)
- `v0/state/A/artifacts.json` (final metadata)
- `v0/state/A/done.flag` (on success)

**Do not touch:**
- Any file under `v0/interfaces/`
- Any other track's state directory
- `v0/build/StemForge.amxd`, `v0/build/StemForge.als`, `v0/build/*.pkg`

**Constraints:**
- `stemforge/cli.py` changes must be additive. Existing CLI behavior unchanged when `--json-events` is absent.
- Binary must be runnable without any environment variables set (beyond those the installer guarantees).

**On blocker:** write `v0/state/A/blocker.md` with details and exit. Do not partially commit a broken binary.
