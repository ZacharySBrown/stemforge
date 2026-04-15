# StemForge v0 — Shippable M4L Device

## Goal

One command on a fresh Mac yields a working StemForge Max for Live device inside Ableton Live 12. Zero manual steps: no Max editor, no venv activation, no "drag this into that folder," no building template tracks by hand.

Success is:

```
curl -fsSL https://stemforge.dev/install | bash
# — or equivalently —
open StemForge-0.0.0.pkg
```

→ Ableton Live opens → File → New from Template → "StemForge" → drop audio → 7 tracks populate with stems + slices + effects within 2 minutes.

## What v0 Ships

| Artifact | Produced by |
|---|---|
| `stemforge-native` — signed universal2 macOS binary, PyInstaller-frozen Python pipeline | Track A |
| `StemForge.amxd` — programmatically generated Max for Live device | Track C |
| `StemForge.als` — programmatically generated Live Set template (7 tracks) | Track D |
| `StemForge-0.0.0.pkg` — signed, notarized installer bundling everything above | Track E |
| GitHub Actions release pipeline | Track F |
| End-to-end test harness | Track G |
| Repackaged Python (`stemforge-core` / `stemforge-native` split) | Track B |

## What v0 Explicitly Does NOT Ship

Deferred to later versions — do not scope-creep into these:

- **ONNX / CoreML inference** → v1. v0 uses PyInstaller-frozen torch.
- **`stemforge~.mxo` Max external** → v2. v0 uses a sidecar binary spawned by `node.script`.
- **Windows / Linux builds** → future. v0 is macOS-only.
- **Analyzer (CLAP/AST) in the native binary** → stays Python-dev-only for v0. The bundled binary exposes `split` and `forge` only.
- **Auto-updater, telemetry, licensing** → not needed for v0.

## Version Roadmap (for context)

| Version | Binary strategy | Native layer | M4L integration |
|---|---|---|---|
| **v0 (this plan)** | PyInstaller-frozen | torch + demucs bundled | sidecar spawned by `node.script` |
| v1 | ONNX Runtime C++ | CoreML EP on Apple Silicon | same sidecar interface |
| v2 | Compiled Max external | ONNX in-process, no subprocess | native `[stemforge~]` object |

The key insight: **v0 fixes distribution. v1 fixes performance. v2 fixes integration.** Do not mix them.

## Architecture (v0)

```
┌──────────────────────────────────────────────────────┐
│ Ableton Live 12                                      │
│                                                      │
│   StemForge.als (template) ─────────────┐            │
│       7 pre-built tracks with FX chains │            │
│                                         ▼            │
│   ┌──────────────────────────────────────────────┐   │
│   │ StemForge.amxd                               │   │
│   │   • file-drop UI                             │   │
│   │   • backend / pipeline selectors             │   │
│   │   • progress UI                              │   │
│   │   • node.script ──► spawns child process ──┐ │   │
│   └────────────────────────────────────────────┼─┘   │
└────────────────────────────────────────────────┼─────┘
                                                 │
                        NDJSON over stdout       │
                        (schema in interfaces/)  │
                                                 ▼
                        ┌───────────────────────────┐
                        │ stemforge-native          │
                        │  (signed universal2)      │
                        │   • torch + demucs        │
                        │   • librosa beat tracking │
                        │   • ffmpeg (bundled)      │
                        │   • model weights         │
                        │     (downloaded 1st run)  │
                        └──────────┬────────────────┘
                                   │
                                   ▼
                        ~/stemforge/processed/<track>/
                            stems.json
                            {drums,bass,...}.wav
                            {drums,bass,...}_beats/
```

## Tracks

Seven parallelizable workstreams. See `v0/tracks/<id>-*.md` for per-track briefs.

| ID | Track | Primary output | Can start |
|---|---|---|---|
| **A** | Native inference binary | `v0/build/stemforge-native` | Immediately |
| **B** | Python package split | updated `pyproject.toml`, lazy imports | Immediately |
| **C** | M4L device generation | `v0/build/StemForge.amxd` | After A has NDJSON binary |
| **D** | .als template generation | `v0/build/StemForge.als` | Immediately |
| **E** | Installer / .pkg | `v0/build/StemForge-0.0.0.pkg` | After A + C + D |
| **F** | CI/CD | `.github/workflows/release.yml` | After A build script exists |
| **G** | Integration tests | `v0/tests/` | After A + C + D |

See `v0/DAG.md` for full execution graph and parallelism plan.

## Shared Memory Convention

Claude Code subagents have no native shared memory. We simulate it with the filesystem. See `v0/SHARED.md` for rules. TL;DR:

- `v0/interfaces/` — read-only contracts (treat as API)
- `v0/state/<track-id>/` — per-track scratch space, status files, progress logs
- `v0/build/` — versioned artifacts flowing between tracks

## Acceptance Criteria (v0 Done)

All of:

1. GitHub tag `v0.0.0` triggers CI, produces `StemForge-0.0.0.pkg` as a release asset.
2. `installer -pkg StemForge-0.0.0.pkg -target /` on a fresh Mac completes without errors.
3. `spctl -a -t exec /usr/local/bin/stemforge-native` → "accepted" (notarization valid).
4. Ableton Live 12 → File → New from Template lists "StemForge".
5. Opening the StemForge template and dragging `test.mp3` onto the device yields:
   - 4+ stem WAVs in `~/stemforge/processed/test/`
   - `stems.json` manifest conforming to schema
   - 4+ duplicated tracks in the live set, each with audio loaded
   - Tempo set to detected BPM
6. `v0/tests/` pytest suite passes without requiring an Ableton instance.

## Non-Goals (Do Not Implement)

- Auto-updating the device
- Cloud sync of processed stems
- Multi-track batch processing UI
- Custom pipeline editor in M4L
- Supporting Demucs models other than `htdemucs` and `htdemucs_6s`
- Any feature not required to pass acceptance criteria above
