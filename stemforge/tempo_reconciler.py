"""
stemforge.tempo_reconciler — multi-source tempo + downbeat detection.

Replaces the librosa-only `slicer.detect_bpm_and_beats()` call on the main
pipeline path. Runs beat-this on the full mix and the drums stem, optionally
isolates kick via LarsNet for tiebreaker, and applies a factor-ratio heuristic
to catch half-time / triplet / cadence-tracking errors before they propagate
into prechop.

Failure mode it solves
----------------------
Half-time hip-hop (e.g. Black Star — Definition, true ~90 BPM, kick on 1+3,
strong half-bar pulse): librosa beat_track locks onto a different rhythmic
layer and reports ~120 BPM. Older beat-this builds had the same blind spot.
Once that wrong BPM is in the manifest, prechop chops the song at the wrong
bar grid and downstream M4L clips are 4 grid-bars but only 3 musical-bars
of audio. Documented at length in the design discussion that produced this
module.

Strategy
--------
1.  Primary detection: beat-this on the full mix (if installed). Returns BPM,
    beat times, downbeat times.
2.  Secondary detection: beat-this on the drums stem. Same outputs.
3.  Reconciliation: if `mix_bpm` and `drums_bpm` disagree by a "round factor"
    (0.5, 0.667, 0.75, 1.333, 1.5, 2.0 — the classic half/double/triplet/
    dotted relationships), one of them is wrong. Optionally run LarsNet kick
    isolation + beat-this on the isolated kick as the tiebreaker — kick is the
    tempo reference in hip-hop. Whichever detector matches the kick wins.
4.  Fallback: if beat-this isn't installed, fall back to librosa with no
    reconciliation. Manifest will record `bpm_source="librosa"` so downstream
    consumers know the result is less trustworthy.

Returns a `ReconciledTempo` with full provenance — every estimate that ran is
preserved so the manifest can capture what each detector saw, not just the
winner. That data is what makes future-fix work tractable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

# Round-number BPM ratios that indicate one detector locked onto the wrong
# rhythmic layer. If mix_bpm / drums_bpm is near one of these (within 1%),
# the disagreement is structural — half-time, double-time, triplet-feel,
# or dotted-eighth confusion — not noise.
SUSPICIOUS_RATIOS: tuple[float, ...] = (
    0.5,  # half-time
    2.0 / 3.0,  # 0.667 — triplet/dotted
    0.75,  # 4/3 inverted — what we saw on Definition
    4.0 / 3.0,  # 1.333 — 4/3
    1.5,  # 3/2 dotted
    2.0,  # double-time
)
RATIO_TOLERANCE = 0.01  # 1% — tight enough to require a "clean" round ratio

ConfidenceLevel = Literal["high", "medium", "low"]
TempoSource = Literal[
    "beat-this:mix",
    "beat-this:drums",
    "beat-this:kick",
    "librosa:mix",
    "librosa:drums",
    "user-override",
]


@dataclass
class TempoEstimate:
    """One detector's reading on one audio source."""

    source: TempoSource
    bpm: float
    beat_times: np.ndarray
    downbeat_times: np.ndarray
    detector: Literal["beat-this", "librosa"]
    audio_label: Literal["mix", "drums", "kick"]

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "bpm": round(float(self.bpm), 3),
            "n_beats": int(len(self.beat_times)),
            "n_downbeats": int(len(self.downbeat_times)),
            "first_downbeat_sec": (
                float(self.downbeat_times[0]) if len(self.downbeat_times) else None
            ),
            "detector": self.detector,
            "audio_label": self.audio_label,
        }


@dataclass
class ReconciledTempo:
    """Final tempo decision plus all the evidence behind it."""

    bpm: float
    beat_times: np.ndarray
    downbeat_times: np.ndarray
    source: TempoSource
    confidence: ConfidenceLevel
    all_estimates: list[TempoEstimate] = field(default_factory=list)
    warning: str | None = None

    def to_dict(self) -> dict:
        return {
            "bpm": round(float(self.bpm), 3),
            "source": self.source,
            "confidence": self.confidence,
            "n_beats": int(len(self.beat_times)),
            "n_downbeats": int(len(self.downbeat_times)),
            "first_downbeat_sec": (
                float(self.downbeat_times[0]) if len(self.downbeat_times) else None
            ),
            "warning": self.warning,
            "all_estimates": [e.to_dict() for e in self.all_estimates],
        }


def _is_suspicious_ratio(a: float, b: float) -> tuple[bool, float | None]:
    """True iff a/b is near one of the SUSPICIOUS_RATIOS within tolerance."""
    if a <= 0 or b <= 0:
        return False, None
    ratio = a / b
    for r in SUSPICIOUS_RATIOS:
        if abs(ratio - r) / r < RATIO_TOLERANCE:
            return True, r
    return False, None


def _detect_beat_this(
    audio_path: Path,
    audio_label: Literal["mix", "drums", "kick"],
    *,
    device: str = "auto",
    dbn: bool = False,
) -> TempoEstimate | None:
    """Run beat-this. Returns None if not installed or it errored."""
    try:
        from beat_this.inference import File2Beats

        from .beat_detect import _select_device
    except ImportError:
        return None

    try:
        resolved = _select_device(device)
        model = File2Beats(checkpoint_path="final0", device=resolved, dbn=dbn)
        beats, downbeats = model(audio_path)
        beats = np.asarray(beats, dtype=float)
        downbeats = np.asarray(downbeats, dtype=float)
        if len(beats) < 2:
            return None
        bpm = 60.0 / float(np.median(np.diff(beats)))
        source: TempoSource = (
            "beat-this:mix" if audio_label == "mix"
            else "beat-this:drums" if audio_label == "drums"
            else "beat-this:kick"
        )
        return TempoEstimate(
            source=source,
            bpm=bpm,
            beat_times=beats,
            downbeat_times=downbeats,
            detector="beat-this",
            audio_label=audio_label,
        )
    except Exception as e:
        logger.warning("beat-this failed on %s (%s): %s", audio_label, audio_path.name, e)
        return None


def _detect_librosa(
    audio_path: Path,
    audio_label: Literal["mix", "drums", "kick"],
) -> TempoEstimate:
    """Always-available librosa fallback. No downbeats."""
    from .slicer import detect_bpm_and_beats

    bpm, beats = detect_bpm_and_beats(audio_path)
    source: TempoSource = (
        "librosa:mix" if audio_label == "mix"
        else "librosa:drums"
        # librosa never runs on kick stem in the reconciler — kick is
        # only used as a beat-this tiebreaker. But keep the type sound.
    )
    return TempoEstimate(
        source=source,
        bpm=float(bpm),
        beat_times=beats,
        downbeat_times=np.array([], dtype=float),
        detector="librosa",
        audio_label=audio_label,
    )


def _isolate_kick(drums_path: Path, output_dir: Path, device: str) -> Path | None:
    """Run LarsNet to isolate kick stem. Returns None if LarsNet unavailable."""
    try:
        from .drum_separator import is_available, separate_drums
    except ImportError:
        return None
    if not is_available():
        return None
    try:
        substems = separate_drums(drums_path, output_dir, device=device)
        kick = substems.get("kick")
        if kick and kick.exists():
            return kick
    except Exception as e:
        logger.warning("LarsNet kick isolation failed: %s", e)
    return None


def reconcile_tempo(
    mix_path: Path | None,
    drums_path: Path | None = None,
    *,
    kick_tiebreaker: bool = True,
    kick_workdir: Path | None = None,
    device: str = "auto",
    dbn: bool = False,
) -> ReconciledTempo:
    """Detect tempo with multi-source reconciliation.

    Args:
        mix_path: Full-mix audio. If None, drums_path must be provided.
        drums_path: Drums stem. Used as a secondary detector and (if a
            disagreement is detected) as the input to LarsNet kick isolation.
        kick_tiebreaker: When mix and drums disagree by a suspicious factor,
            run LarsNet → beat-this on the isolated kick to break the tie.
            Costs ~10 seconds; only triggered on disagreement.
        kick_workdir: Where to write the LarsNet sub-stems. Required iff
            `kick_tiebreaker=True` and a tiebreaker actually fires.
        device: Torch device for beat-this and LarsNet ("auto"|"cpu"|"mps"|"cuda").
        dbn: beat-this DBN postprocessor. Default False — DBN requires madmom
            which is rarely installed and the front-end alone is reliable on
            most material.

    Returns:
        ReconciledTempo with the chosen BPM + downbeats and the full evidence
        trail.
    """
    if mix_path is None and drums_path is None:
        raise ValueError("at least one of mix_path or drums_path is required")

    estimates: list[TempoEstimate] = []
    mix_est: TempoEstimate | None = None
    drums_est: TempoEstimate | None = None

    # ── Primary: beat-this on mix ────────────────────────────────────────
    if mix_path is not None:
        mix_est = _detect_beat_this(mix_path, "mix", device=device, dbn=dbn)
        if mix_est is not None:
            estimates.append(mix_est)

    # ── Secondary: beat-this on drums ─────────────────────────────────────
    if drums_path is not None:
        drums_est = _detect_beat_this(drums_path, "drums", device=device, dbn=dbn)
        if drums_est is not None:
            estimates.append(drums_est)

    # ── If beat-this is unavailable entirely, fall back to librosa ───────
    if mix_est is None and drums_est is None:
        # beat-this not installed (or failed everywhere). Use librosa.
        primary_path = drums_path or mix_path
        primary_label: Literal["mix", "drums"] = "drums" if drums_path else "mix"
        assert primary_path is not None
        lr = _detect_librosa(primary_path, primary_label)
        estimates.append(lr)
        return ReconciledTempo(
            bpm=lr.bpm,
            beat_times=lr.beat_times,
            downbeat_times=lr.downbeat_times,
            source=lr.source,
            confidence="low",
            all_estimates=estimates,
            warning="beat-this unavailable; librosa-only detection (no downbeats).",
        )

    # ── Ratio reconciliation ─────────────────────────────────────────────
    # When both mix + drums fired, see if they agree.
    if mix_est is not None and drums_est is not None:
        ratio_suspicious, ratio_value = _is_suspicious_ratio(mix_est.bpm, drums_est.bpm)
        bpm_close = abs(mix_est.bpm - drums_est.bpm) / max(mix_est.bpm, drums_est.bpm) < 0.005

        if bpm_close:
            # They agree — high confidence in the mix estimate.
            return ReconciledTempo(
                bpm=mix_est.bpm,
                beat_times=mix_est.beat_times,
                downbeat_times=mix_est.downbeat_times,
                source=mix_est.source,
                confidence="high",
                all_estimates=estimates,
            )

        if ratio_suspicious and kick_tiebreaker and drums_path is not None:
            # Round-factor disagreement — run kick tiebreaker.
            if kick_workdir is None:
                kick_workdir = drums_path.parent / "tempo_reconciler_substems"
            kick_path = _isolate_kick(drums_path, kick_workdir, device)
            if kick_path is not None:
                kick_est = _detect_beat_this(kick_path, "kick", device=device, dbn=dbn)
                if kick_est is not None:
                    estimates.append(kick_est)
                    # Pick the candidate (mix or drums) closest to kick.
                    mix_dist = abs(mix_est.bpm - kick_est.bpm)
                    drums_dist = abs(drums_est.bpm - kick_est.bpm)
                    winner = mix_est if mix_dist <= drums_dist else drums_est
                    return ReconciledTempo(
                        bpm=winner.bpm,
                        beat_times=winner.beat_times,
                        downbeat_times=winner.downbeat_times,
                        source=winner.source,
                        confidence="medium",
                        all_estimates=estimates,
                        warning=(
                            f"mix ({mix_est.bpm:.2f}) and drums ({drums_est.bpm:.2f}) "
                            f"disagreed by ratio {ratio_value:.3f}; kick tiebreaker "
                            f"({kick_est.bpm:.2f}) preferred {winner.audio_label}."
                        ),
                    )

        # Disagreement without a clean half/double/triplet relationship.
        # The kick tiebreaker only fires for clean round-factor ratios
        # because LarsNet costs ~10s and is most informative when one
        # detector locked onto a known wrong layer. For "fuzzy" disagreements
        # the kick reading is unlikely to be cleaner than the mix reading,
        # so we prefer mix (more rhythmic context) and flag low confidence.
        winner = mix_est
        ratio = mix_est.bpm / drums_est.bpm
        return ReconciledTempo(
            bpm=winner.bpm,
            beat_times=winner.beat_times,
            downbeat_times=winner.downbeat_times,
            source=winner.source,
            confidence="low",
            all_estimates=estimates,
            warning=(
                f"mix ({mix_est.bpm:.2f}) and drums ({drums_est.bpm:.2f}) "
                f"disagreed (ratio {ratio:.3f}) but the disagreement is not a "
                f"clean half/double/triplet factor — no tiebreaker fired. "
                f"Using mix BPM. If this BPM looks wrong, the source has an "
                f"unusual rhythmic structure."
            ),
        )

    # Only one estimate fired — single-source result.
    only = mix_est or drums_est
    assert only is not None
    return ReconciledTempo(
        bpm=only.bpm,
        beat_times=only.beat_times,
        downbeat_times=only.downbeat_times,
        source=only.source,
        confidence="medium",
        all_estimates=estimates,
    )


__all__ = [
    "ConfidenceLevel",
    "ReconciledTempo",
    "SUSPICIOUS_RATIOS",
    "TempoEstimate",
    "TempoSource",
    "reconcile_tempo",
]
