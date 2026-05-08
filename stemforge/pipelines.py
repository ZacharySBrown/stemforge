"""
stemforge.pipelines — load pipeline YAMLs and apply post-split steps.

Today most of the pipeline YAMLs (default, glitch, ambient, ...) are read by
the M4L device for per-stem track templating. But a pipeline can also declare
Python-side post-split steps. The first such step is `prechop:` — when
present, after stem separation finishes, the runner calls `stemforge.prechop`
on the stems dict with the configured bar/pad parameters.

Schema (all top-level — siblings, not nested under `pipelines:`):

    name: arrangement
    description: ...
    prechop:
      bars: 4
      pad_bars: 1
      pad_last: true
      beats_per_bar: 4

`prechop:` is optional. If absent, `run_post_split_steps` is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINES_DIR = REPO_ROOT / "pipelines"


@dataclass
class PrechopConfig:
    # TODO(time-sig): support 6/8, 3/4 — manifest already records beats_per_bar
    # but the loader assumes 4/4 (Live's clock is quarter-note based; non-4/4
    # signatures would also need a `denominator` field added here + threaded
    # into prechop_manifest.json so the M4L loader can adjust clip lengths).
    bars: int = 4
    pad_bars: int = 1
    pad_last: bool = True
    beats_per_bar: int = 4

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PrechopConfig | None":
        # `None` means no prechop block; `{}` means "use defaults".
        if data is None:
            return None
        return cls(
            bars=int(data.get("bars", 4)),
            pad_bars=int(data.get("pad_bars", 1)),
            pad_last=bool(data.get("pad_last", True)),
            beats_per_bar=int(data.get("beats_per_bar", 4)),
        )


@dataclass
class PipelineConfig:
    name: str
    description: str = ""
    prechop: PrechopConfig | None = None
    raw: dict[str, Any] | None = None  # full YAML for downstream consumers


def load_pipeline(name: str, pipelines_dir: Path | None = None) -> PipelineConfig:
    """Load a pipeline yaml by name. Falls back to a no-config default.

    Search order: <pipelines_dir>/<name>.yaml → <pipelines_dir>/<name>.yml.
    If neither exists, returns a default PipelineConfig (so passing
    --pipeline default keeps working even though `default.yaml` has no
    Python-side blocks today).
    """
    base = pipelines_dir or PIPELINES_DIR
    for ext in (".yaml", ".yml"):
        candidate = base / f"{name}{ext}"
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text()) or {}
            return PipelineConfig(
                name=str(data.get("name", name)),
                description=str(data.get("description", "")),
                prechop=PrechopConfig.from_dict(data.get("prechop")),
                raw=data,
            )
    return PipelineConfig(name=name, description="", prechop=None, raw=None)


def run_post_split_steps(
    pipeline: PipelineConfig,
    stem_paths: dict[str, Path],
    output_dir: Path,
    *,
    bpm: float,
    first_downbeat_sec: float = 0.0,
    pre_bars: int = 0,
    pad_pre_bars: int | None = None,
    pad_post_bars: int | None = None,
    emit_partial: bool | None = None,
) -> dict[str, Any]:
    """Apply any Python-side post-split steps from the pipeline.

    `first_downbeat_sec` forwarded to prechop so chunks anchor on the
    first detected musical bar instead of the audio file's frame zero.
    `pre_bars` includes that many bars of intro material before bar 1.
    `pad_pre_bars` / `pad_post_bars` override the symmetric `pad_bars`
    config when set (None = use the pipeline's `pad_bars`).
    `emit_partial` controls the leading-partial chunk gate: True (CLI
    default) always emits when boundary conditions allow; False skips;
    None defers to prechop's auto-decide. The CLI flips this to True
    explicitly so callers see deterministic behavior.

    Returns a small status dict keyed by step name. Today: just `prechop`.
    """
    status: dict[str, Any] = {}

    if pipeline.prechop is not None:
        from .prechop import prechop as run_prechop

        manifest_path = run_prechop(
            stem_paths,
            output_dir,
            bpm=bpm,
            bars=pipeline.prechop.bars,
            pad_bars=pipeline.prechop.pad_bars,
            pad_last=pipeline.prechop.pad_last,
            beats_per_bar=pipeline.prechop.beats_per_bar,
            first_downbeat_sec=first_downbeat_sec,
            pre_bars=pre_bars,
            pad_pre_bars=pad_pre_bars,
            pad_post_bars=pad_post_bars,
            emit_partial=emit_partial,
        )
        status["prechop"] = {
            "manifest": str(manifest_path),
            "bars": pipeline.prechop.bars,
            "pad_bars": pipeline.prechop.pad_bars,
            "pad_pre_bars": pad_pre_bars,
            "pad_post_bars": pad_post_bars,
            "first_downbeat_sec": float(first_downbeat_sec),
            "pre_bars": int(pre_bars),
            "emit_partial": emit_partial,
        }

    return status


__all__ = [
    "PIPELINES_DIR",
    "PipelineConfig",
    "PrechopConfig",
    "load_pipeline",
    "run_post_split_steps",
]
