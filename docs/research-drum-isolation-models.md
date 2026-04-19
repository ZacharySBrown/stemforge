# Research: Drum One-Shot Isolation — HuggingFace Models & Tools

> Research completed 2026-04-19. Models and tools that can replace or augment
> our current onset-detection-based one-shot extraction pipeline.

---

## The Problem

Our current pipeline: `htdemucs drums.wav → librosa onset detection → windowed extraction → spectral heuristic classification`. Results are poor — hits too long, multiple events captured, stem bleed, wrong classifications.

## Recommended Upgrade Path

### Tier 1: Quick Wins (days of work)

**1. Replace spectral classifier with CLAP/AST (already loaded)**
- We already have both models in `analyzer.py`
- Route each one-shot through CLAP with labels: `["kick drum", "snare drum", "closed hi-hat", "open hi-hat", "tom drum", "cymbal crash", "rimshot", "hand clap"]`
- Pure code change in `drum_classifier.py`, no new models to download

**2. Replace librosa onset detection with madmom**
- `pip install madmom`
- `CNNOnsetProcessor` — CNN-based, specifically designed for percussive onsets
- Drop-in replacement for `detect_onsets_multiband()` in `oneshot.py`
- Much more accurate for drums than librosa's spectral flux

### Tier 2: Game-Changer (1-2 weeks)

**3. LarsNet — Drum Sub-Stem Separation (RECOMMENDED)**
- **GitHub:** https://github.com/polimi-ispl/larsnet
- Separates drum mixture → 5 sub-stems: **kick, snare, toms, hi-hat, cymbals**
- Architecture: parallel U-Nets (one per drum class)
- Model size: 562 MB
- License: CC BY-NC 4.0
- **Pipeline fit:** After htdemucs produces `drums.wav`, run LarsNet to get `kick.wav`, `snare.wav`, `hihat.wav`. Then simple onset detection on each clean sub-stem. Classification becomes unnecessary — the sub-stem identity IS the classification. Eliminates bleed entirely.

**4. DrumSep MDX23C (Best SDR scores)**
- Available via ZFTurbo/Music-Source-Separation-Training
- Output: kick, snare, toms, hi-hat, ride, crash (5-6 stems)
- SDR: kick 16.66, snare 11.53, toms 12.33
- Best measured quality but more complex setup

**5. DrumSep (HTDemucs variant — easiest integration)**
- **GitHub:** https://github.com/inagoy/drumsep
- Same architecture as htdemucs (already in our stack)
- Output: kick, snare, cymbals, toms (4 stems)
- License: MIT
- Easiest to integrate since we already have Demucs infrastructure

### Tier 3: Next-Generation (experimental)

**6. DOSE — Direct One-Shot Extraction**
- **GitHub:** https://github.com/HSUNEH/DOSE
- Decoder-only Transformer that extracts clean one-shots directly from mixture
- Separate models for kick, snare, hi-hat
- Published ICASSP 2025
- Skips separation + slicing entirely

**7. Inverse Drum Machine (IDM)**
- **GitHub:** https://github.com/bernardo-torres/inverse-drum-machine
- Joint transcription + one-shot SYNTHESIS
- Detects onsets, extracts velocities, AND synthesizes clean one-shot samples
- Clean one-shots because they're generated, not extracted (no bleed)
- Apache 2.0 license, published TASLP 2026

---

## Drum Transcription Models (onset detection + classification)

**8. ADTOF — Automatic Drum Transcription**
- **GitHub:** https://github.com/MZehren/ADTOF
- CRNN detecting kick, snare, hi-hat, toms, cymbals with precise onset times
- 359 hours of training data
- Replaces both onset detection AND classification

**9. ADTLib**
- **GitHub:** https://github.com/CarlSouthall/ADTLib
- `pip install ADTLib` then `ADT Drum.wav`
- Returns onset times labeled by drum type
- BSD-2-Clause

---

## Audio Classification Models

**10. DunnBC22/wav2vec2-base-Drum_Kit_Sounds**
- **HuggingFace:** https://huggingface.co/DunnBC22/wav2vec2-base-Drum_Kit_Sounds
- wav2vec2 fine-tuned specifically on drum kit sounds
- Classes: kick, overheads, snare, toms
- 78.1% accuracy

**11. BEATs** — State-of-the-art audio classifier (0.485 mAP on AudioSet)

**12. PANNs** — AudioSet CNNs, good as feature extractor

---

## Text-Guided Separation (Creative)

**13. AudioSep — "Separate Anything You Describe"**
- **GitHub:** https://github.com/Audio-AGI/AudioSep
- Run 3-4 times with prompts: "kick drum", "snare drum", "hi-hat"
- MIT license, works but less precise than dedicated drum separators

**14. ZeroSep** — Zero-shot using diffusion models (NeurIPS 2025, experimental)

---

## Datasets for Training/Evaluation

| Dataset | Content | Size |
|---------|---------|------|
| StemGMD | 9-piece kit, 10 drumkits, isolated stems | 1.13 TB |
| RMOD | 3375 kick + 1801 snare + 1278 hi-hat one-shots | ~6K samples |
| IDMT-SMT-Drums | 608 WAVs with onset annotations | ~2 hours |
| MDB Drums | 23 tracks, 7994 annotated onsets, 6 classes | 23 tracks |
| Kaggle Drum Kit Sounds | Labeled kick/snare/overheads/toms | varied |

---

## Integration Recommendation for StemForge

```
CURRENT:
  htdemucs → drums.wav → librosa onsets → window extract → spectral classify
  (poor quality)

RECOMMENDED (Tier 1 quick fix):
  htdemucs → drums.wav → madmom CNN onsets → window extract → CLAP classify
  (better onsets + better classification, same architecture)

RECOMMENDED (Tier 2 game-changer):
  htdemucs → drums.wav → LarsNet → kick.wav / snare.wav / hihat.wav / ...
    → simple onset detect per sub-stem → extract → done (no classification needed)
  (clean isolation, no bleed, classification-free)

FUTURE (Tier 3):
  htdemucs → drums.wav → DOSE → clean one-shot kick / snare / hihat
  (end-to-end, no intermediate steps)
```

### Priority Action Items

1. **Now:** Try CLAP classification on existing one-shots (already have the model)
2. **Next:** Install madmom, replace onset detection
3. **Big win:** Integrate LarsNet for drum sub-stem separation
4. **Long-term:** Evaluate DOSE for direct one-shot extraction

---

## LarsNet Test Results (2026-04-19)

**Tested on Apple Silicon (MPS) with two tracks:**

### The Champ (funk, 112 BPM, 157s drum stem)
- **Processing time:** 6 seconds on MPS
- **Sub-stems produced:**
  - kick: RMS 0.0913, peak 0.876 — strong, dominant
  - snare: RMS 0.0521, peak 1.000 — clear
  - hihat: RMS 0.0158, peak 0.795 — present
  - cymbals: RMS 0.0012, peak 0.053 — sparse (correct for funk break)
  - toms: RMS 0.0021, peak 0.393 — sparse (correct)
- **Kick one-shots extracted:** 285 onsets, 150-300ms, RMS 0.14-0.23
- **Quality:** Clean isolation, no bleed, no misclassification

### Can I Kick It (hip hop, 98 BPM, 265s drum stem)
- **Processing time:** 7 seconds on MPS
- **Sub-stems produced:**
  - kick: RMS 0.0685, peak 0.904
  - snare: RMS 0.0750, peak 1.000
  - toms: RMS 0.1080, peak 0.988 — strong (congas from Lou Reed sample)
  - hihat: RMS 0.0143, peak 0.696
  - cymbals: RMS 0.0095, peak 0.505

### Verdict

LarsNet eliminates the entire classification problem. Once you have `kick.wav`,
simple onset detection produces clean one-shots because there's no bleed.
The 6-7 second processing time on MPS makes it viable for the interactive
StemForge pipeline.

**Model location:** `/tmp/larsnet/` (cloned repo + pretrained models)
**To reproduce:**
```bash
cd /tmp/larsnet
python separate.py -i <dir_with_drums.wav> -o <output_dir> -d mps
```
