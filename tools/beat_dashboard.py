#!/usr/bin/env python3
"""beat_dashboard.py — Generate an interactive HTML dashboard for beat alignment analysis.

Analyzes all processed tracks and produces a self-contained HTML file with:
- Summary table (sortable by any metric)
- Per-track deep dive (bar durations, IBI distribution, energy timeline)
- Flagged segments with audio playback + draggable beat markers

Usage:
    uv run python tools/beat_dashboard.py
    uv run python tools/beat_dashboard.py --output dashboard.html
    uv run python tools/beat_dashboard.py --tracks the_champ_original_version benjamins
"""
from __future__ import annotations

import argparse
import json
import html as html_mod
import sys
from pathlib import Path

import numpy as np
import librosa

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stemforge.slicer import detect_bpm_and_beats
from stemforge.beat_align import (
    filter_ghost_beats,
    find_best_downbeat_offset,
    apply_downbeat_offset,
    diagnose_drift,
)

# beat-this is optional
try:
    from stemforge.beat_detect import detect_beats_and_downbeats
    HAS_BEAT_THIS = True
except ImportError:
    HAS_BEAT_THIS = False


def analyze_track(track_dir: Path, time_sig: int = 4) -> dict | None:
    """Run full analysis on a single track."""
    drums = track_dir / "drums.wav"
    if not drums.exists():
        return None

    track_name = track_dir.name

    try:
        y, sr = librosa.load(str(drums), sr=None, mono=True)
    except Exception as e:
        return {"track": track_name, "error": str(e)}

    duration = len(y) / sr

    try:
        bpm, beat_times = detect_bpm_and_beats(drums)
    except Exception as e:
        return {"track": track_name, "error": f"beat detection failed: {e}"}

    # Inter-beat intervals
    ibis = np.diff(beat_times)
    median_ibi = float(np.median(ibis)) if len(ibis) > 0 else 0

    # Bar durations (original)
    bar_starts_orig = beat_times[::time_sig]
    bar_durs_orig = np.diff(bar_starts_orig)
    interior_orig = bar_durs_orig[:-1] if len(bar_durs_orig) > 1 else bar_durs_orig
    bar_median = float(np.median(interior_orig)) if len(interior_orig) > 0 else 0
    bar_cv_orig = float(interior_orig.std() / interior_orig.mean() * 100) if len(interior_orig) > 1 else 0

    # Corrections
    cleaned, ghosts_removed = filter_ghost_beats(beat_times)
    offset = find_best_downbeat_offset(drums, cleaned, time_sig=time_sig)
    corrected = apply_downbeat_offset(cleaned, offset) if offset > 0 else cleaned

    bar_starts_corr = corrected[::time_sig]
    bar_durs_corr = np.diff(bar_starts_corr)
    interior_corr = bar_durs_corr[:-1] if len(bar_durs_corr) > 1 else bar_durs_corr
    bar_cv_corr = float(interior_corr.std() / interior_corr.mean() * 100) if len(interior_corr) > 1 else 0

    correction_applied = bar_cv_corr < bar_cv_orig and (ghosts_removed > 0 or offset > 0)

    # Onset energy scores per offset
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_times_arr = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr)

    offset_scores = []
    for off in range(time_sig):
        shifted = beat_times[off:]
        bs = shifted[::time_sig]
        score = float(sum(
            onset_env[min(np.searchsorted(onset_times_arr, t), len(onset_env) - 1)]
            for t in bs
        ))
        offset_scores.append(score)

    # Energy timeline (1-second windows)
    energy_timeline = []
    hop = sr
    for i in range(0, len(y) - hop, hop):
        rms = float(np.sqrt(np.mean(y[i:i + hop] ** 2)))
        energy_timeline.append(rms)

    # IBI histogram
    if len(ibis) > 0:
        ibi_bpms = (60.0 / ibis).tolist()
    else:
        ibi_bpms = []

    # Deviant bars
    deviant_bars = []
    active_durs = interior_orig if not correction_applied else interior_corr
    active_starts = bar_starts_orig if not correction_applied else bar_starts_corr
    active_median = float(np.median(active_durs)) if len(active_durs) > 0 else 0

    for i in range(len(active_durs)):
        dev = (active_durs[i] - active_median) / active_median * 100 if active_median > 0 else 0
        if abs(dev) > 5:
            deviant_bars.append({
                "bar": i + 1,
                "time": float(active_starts[i]),
                "duration": float(active_durs[i]),
                "deviation_pct": round(dev, 1),
            })

    # Drift analysis
    drift = diagnose_drift(drums, n_segments=6)

    # Per-bar duration list for charts
    bar_durations_list = [
        {"bar": i + 1, "duration": float(d), "time": float(active_starts[i])}
        for i, d in enumerate(active_durs)
    ]

    # beat-this neural downbeat analysis (on drums stem AND full mix if available)
    bt_drums = {"bpm": 0, "bars": 0, "cv": -1, "downbeats": 0}
    bt_mix = {"bpm": 0, "bars": 0, "cv": -1, "downbeats": 0}
    bt_winner = "librosa"

    if HAS_BEAT_THIS:
        # Drums stem
        try:
            bd_bpm, bd_beats, bd_db = detect_beats_and_downbeats(drums)
            if len(bd_db) > 2:
                bd_durs = np.diff(bd_db)
                bd_cv = float(bd_durs[:-1].std() / bd_durs[:-1].mean() * 100)
                bt_drums = {"bpm": round(bd_bpm, 1), "bars": len(bd_durs), "cv": round(bd_cv, 2), "downbeats": len(bd_db)}
        except Exception:
            pass

        # Full mix (if source audio available)
        source_audio = None
        source_manifest = track_dir / "stems.json"
        if source_manifest.exists():
            try:
                src_data = json.loads(source_manifest.read_text())
                src_path = Path(src_data.get("source_file", ""))
                if src_path.exists():
                    source_audio = src_path
            except (json.JSONDecodeError, KeyError):
                pass

        if source_audio:
            try:
                bm_bpm, bm_beats, bm_db = detect_beats_and_downbeats(source_audio)
                if len(bm_db) > 2:
                    bm_durs = np.diff(bm_db)
                    bm_cv = float(bm_durs[:-1].std() / bm_durs[:-1].mean() * 100)
                    bt_mix = {"bpm": round(bm_bpm, 1), "bars": len(bm_durs), "cv": round(bm_cv, 2), "downbeats": len(bm_db)}
            except Exception:
                pass

        # Determine winner
        candidates = [("librosa", bar_cv_orig)]
        if bt_drums["cv"] >= 0:
            candidates.append(("bt-drums", bt_drums["cv"]))
        if bt_mix["cv"] >= 0:
            candidates.append(("bt-mix", bt_mix["cv"]))
        bt_winner = min(candidates, key=lambda x: x[1])[0]

    return {
        "track": track_name,
        "duration_s": round(duration, 1),
        "bpm": round(bpm, 2),
        "beat_count": len(beat_times),
        "bar_count": len(interior_orig),
        "time_sig": time_sig,
        "median_bar_duration": round(bar_median, 4),
        "bar_cv_original": round(bar_cv_orig, 2),
        "bar_cv_corrected": round(bar_cv_corr, 2),
        "correction_applied": correction_applied,
        "ghosts_removed": ghosts_removed,
        "downbeat_offset": offset,
        "offset_scores": [round(s, 1) for s in offset_scores],
        "median_ibi": round(median_ibi, 4),
        "ibi_bpms": [round(b, 1) for b in ibi_bpms],
        "energy_timeline": [round(e, 4) for e in energy_timeline],
        "deviant_bars": deviant_bars,
        "deviant_count": len(deviant_bars),
        "bar_durations": bar_durations_list,
        "drift": {
            "tempos": [round(t, 1) for t in drift["tempos"]],
            "mean": round(drift["mean"], 1),
            "std": round(drift["std"], 1),
            "drift_score": round(drift["drift_score"], 2),
        },
        "bt_drums": bt_drums,
        "bt_mix": bt_mix,
        "bt_winner": bt_winner,
        "has_source_audio": source_audio is not None if HAS_BEAT_THIS else False,
        "drums_path": str(drums),
    }


def generate_html(data: list[dict], output_path: Path) -> None:
    """Generate the self-contained HTML dashboard."""
    data_json = json.dumps(data, indent=None)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StemForge Beat Analysis Dashboard</title>
<style>
:root {{
    --bg: #1a1a2e;
    --surface: #16213e;
    --surface2: #0f3460;
    --accent: #e94560;
    --accent2: #533483;
    --text: #e0e0e0;
    --text-dim: #888;
    --green: #4ade80;
    --yellow: #fbbf24;
    --red: #f87171;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    background: var(--bg);
    color: var(--text);
    padding: 20px;
    font-size: 13px;
}}
h1 {{
    color: var(--accent);
    font-size: 24px;
    margin-bottom: 4px;
}}
.subtitle {{ color: var(--text-dim); margin-bottom: 20px; }}
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
}}
th, td {{
    padding: 6px 10px;
    text-align: left;
    border-bottom: 1px solid #333;
}}
th {{
    background: var(--surface);
    color: var(--accent);
    cursor: pointer;
    user-select: none;
    position: sticky;
    top: 0;
    z-index: 10;
}}
th:hover {{ background: var(--surface2); }}
tr:hover {{ background: rgba(233, 69, 96, 0.08); }}
.good {{ color: var(--green); }}
.warn {{ color: var(--yellow); }}
.bad {{ color: var(--red); }}
.tag {{
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 11px;
}}
.tag-applied {{ background: rgba(74, 222, 128, 0.2); color: var(--green); }}
.tag-reverted {{ background: rgba(248, 113, 113, 0.1); color: var(--text-dim); }}
.tag-none {{ background: rgba(136, 136, 136, 0.1); color: var(--text-dim); }}
.detail {{
    display: none;
    background: var(--surface);
    padding: 16px;
    margin: 8px 0;
    border-radius: 8px;
    border: 1px solid #333;
}}
.detail.open {{ display: block; }}
.detail h3 {{
    color: var(--accent);
    margin-bottom: 12px;
}}
.charts {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin: 12px 0;
}}
.chart-box {{
    background: var(--bg);
    border-radius: 6px;
    padding: 12px;
    border: 1px solid #333;
}}
.chart-box h4 {{
    color: var(--text-dim);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
}}
canvas {{ width: 100%; height: 120px; }}
.bar-list {{
    max-height: 200px;
    overflow-y: auto;
    font-size: 12px;
}}
.bar-item {{
    padding: 3px 8px;
    display: flex;
    justify-content: space-between;
    border-bottom: 1px solid #222;
}}
.bar-item:hover {{ background: rgba(233, 69, 96, 0.1); }}
.bar-item .dev {{ font-weight: bold; }}
.energy-bar {{
    display: inline-block;
    height: 14px;
    background: var(--accent2);
    border-radius: 2px;
    vertical-align: middle;
}}
.metric-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin: 12px 0;
}}
.metric {{
    background: var(--bg);
    border-radius: 6px;
    padding: 10px;
    text-align: center;
    border: 1px solid #333;
}}
.metric .value {{
    font-size: 20px;
    font-weight: bold;
    color: var(--accent);
}}
.metric .label {{
    font-size: 10px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-top: 4px;
}}
.player {{
    background: var(--bg);
    border-radius: 6px;
    padding: 12px;
    margin: 8px 0;
    border: 1px solid #333;
}}
.player button {{
    background: var(--accent);
    color: white;
    border: none;
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
    margin-right: 8px;
}}
.player button:hover {{ opacity: 0.8; }}
.waveform-container {{
    position: relative;
    margin: 8px 0;
    cursor: crosshair;
}}
.beat-marker {{
    position: absolute;
    top: 0;
    width: 2px;
    height: 100%;
    background: var(--accent);
    opacity: 0.6;
    cursor: ew-resize;
}}
.beat-marker:hover {{ opacity: 1; width: 3px; }}
.beat-marker.adjusted {{ background: var(--green); }}
#summary-stats {{
    display: flex;
    gap: 20px;
    margin: 16px 0;
    flex-wrap: wrap;
}}
#summary-stats .stat {{
    background: var(--surface);
    padding: 12px 20px;
    border-radius: 8px;
    border: 1px solid #333;
}}
#summary-stats .stat .val {{
    font-size: 28px;
    font-weight: bold;
    color: var(--accent);
}}
#summary-stats .stat .lbl {{
    font-size: 11px;
    color: var(--text-dim);
}}
.filter-bar {{
    margin: 12px 0;
    display: flex;
    gap: 8px;
    align-items: center;
}}
.filter-bar input {{
    background: var(--surface);
    border: 1px solid #444;
    color: var(--text);
    padding: 4px 8px;
    border-radius: 4px;
    font-family: inherit;
    font-size: 12px;
}}
.filter-bar select {{
    background: var(--surface);
    border: 1px solid #444;
    color: var(--text);
    padding: 4px 8px;
    border-radius: 4px;
    font-family: inherit;
}}
</style>
</head>
<body>

<h1>StemForge Beat Analysis Dashboard</h1>
<p class="subtitle">Beat grid quality, alignment corrections, and segment validation</p>

<div id="summary-stats"></div>

<div class="filter-bar">
    <input type="text" id="search" placeholder="Search tracks..." oninput="filterTable()">
    <select id="filter-status" onchange="filterTable()">
        <option value="all">All tracks</option>
        <option value="corrected">Corrections applied</option>
        <option value="issues">Has issues (CV &gt; 3%)</option>
        <option value="clean">Clean (CV &lt; 1%)</option>
    </select>
</div>

<table id="main-table">
    <thead>
        <tr>
            <th onclick="sortTable(0)">Track</th>
            <th onclick="sortTable(1)">BPM</th>
            <th onclick="sortTable(2)">Bars</th>
            <th onclick="sortTable(3)">CV% (lib)</th>
            <th onclick="sortTable(4)">CV% (bt-drm)</th>
            <th onclick="sortTable(5)">CV% (bt-mix)</th>
            <th onclick="sortTable(6)">Best</th>
            <th onclick="sortTable(7)">Ghosts</th>
            <th onclick="sortTable(8)">Offset</th>
            <th onclick="sortTable(9)">Deviant</th>
            <th onclick="sortTable(10)">Drift</th>
            <th onclick="sortTable(11)">Status</th>
        </tr>
    </thead>
    <tbody id="table-body"></tbody>
</table>

<div id="details-container"></div>

<script>
const DATA = {data_json};

function init() {{
    renderSummary();
    renderTable();
    renderDetails();
}}

function renderSummary() {{
    const el = document.getElementById('summary-stats');
    const total = DATA.length;
    const errors = DATA.filter(d => d.error).length;
    const valid = DATA.filter(d => !d.error);
    const corrected = valid.filter(d => d.correction_applied).length;
    const clean = valid.filter(d => d.bar_cv_original < 1).length;
    const issues = valid.filter(d => d.bar_cv_original > 3).length;
    const avgCV = valid.length ? (valid.reduce((s, d) => s + d.bar_cv_original, 0) / valid.length).toFixed(1) : 0;
    const btWins = valid.filter(d => d.bt_winner && d.bt_winner !== 'librosa').length;
    const hasBT = valid.some(d => d.bt_drums && d.bt_drums.cv >= 0);

    el.innerHTML = `
        <div class="stat"><div class="val">${{total}}</div><div class="lbl">Tracks analyzed</div></div>
        <div class="stat"><div class="val">${{clean}}</div><div class="lbl">Clean (CV &lt; 1%)</div></div>
        <div class="stat"><div class="val">${{issues}}</div><div class="lbl">Issues (CV &gt; 3%)</div></div>
        <div class="stat"><div class="val">${{corrected}}</div><div class="lbl">Heuristic corrections</div></div>
        <div class="stat"><div class="val">${{avgCV}}%</div><div class="lbl">Avg CV (librosa)</div></div>
        ${{hasBT ? `<div class="stat"><div class="val">${{btWins}}</div><div class="lbl">beat-this wins</div></div>` : ''}}
    `;
}}

function cvClass(cv) {{
    if (cv < 1) return 'good';
    if (cv < 3) return 'warn';
    return 'bad';
}}

function btCvCell(bt) {{
    if (!bt || bt.cv < 0) return '<td style="color:var(--text-dim)">-</td>';
    return `<td class="${{cvClass(bt.cv)}}">${{bt.cv}}%</td>`;
}}

function winnerTag(w) {{
    if (w === 'bt-mix') return '<span class="tag tag-applied">bt-mix</span>';
    if (w === 'bt-drums') return '<span class="tag tag-applied">bt-drums</span>';
    return '<span class="tag tag-none">librosa</span>';
}}

function renderTable() {{
    const tbody = document.getElementById('table-body');
    tbody.innerHTML = DATA.filter(d => !d.error).map((d, i) => {{
        const status = d.correction_applied ? '<span class="tag tag-applied">corrected</span>' :
                       (d.ghosts_removed > 0 || d.downbeat_offset > 0) ? '<span class="tag tag-reverted">reverted</span>' :
                       '<span class="tag tag-none">clean</span>';
        return `<tr data-idx="${{i}}" onclick="toggleDetail(${{i}})">
            <td>${{d.track}}</td>
            <td>${{d.bpm}}</td>
            <td>${{d.bar_count}}</td>
            <td class="${{cvClass(d.bar_cv_original)}}">${{d.bar_cv_original}}%</td>
            ${{btCvCell(d.bt_drums)}}
            ${{btCvCell(d.bt_mix)}}
            <td>${{winnerTag(d.bt_winner)}}</td>
            <td>${{d.ghosts_removed || '-'}}</td>
            <td>${{d.downbeat_offset || '-'}}</td>
            <td class="${{d.deviant_count > 5 ? 'bad' : d.deviant_count > 0 ? 'warn' : 'good'}}">${{d.deviant_count}}</td>
            <td class="${{d.drift.drift_score > 5 ? 'bad' : d.drift.drift_score > 2 ? 'warn' : 'good'}}">${{d.drift.drift_score}}</td>
            <td>${{status}}</td>
        </tr>`;
    }}).join('');
}}

function renderDetails() {{
    const container = document.getElementById('details-container');
    container.innerHTML = DATA.filter(d => !d.error).map((d, i) => {{
        const energyMax = Math.max(...d.energy_timeline, 0.001);
        const energyBars = d.energy_timeline.map(e =>
            `<span class="energy-bar" style="width:${{Math.round(e/energyMax*60)}}px" title="${{e.toFixed(4)}}"></span>`
        ).join('');

        const deviantRows = d.deviant_bars.slice(0, 20).map(b =>
            `<div class="bar-item">
                <span>Bar ${{b.bar}} @ ${{b.time.toFixed(1)}}s</span>
                <span>${{b.duration.toFixed(4)}}s</span>
                <span class="dev ${{Math.abs(b.deviation_pct) > 8 ? 'bad' : 'warn'}}">${{b.deviation_pct > 0 ? '+' : ''}}${{b.deviation_pct}}%</span>
            </div>`
        ).join('');

        const offsetBars = d.offset_scores.map((s, oi) => {{
            const maxScore = Math.max(...d.offset_scores);
            const pct = Math.round(s / maxScore * 100);
            const best = oi === d.downbeat_offset ? ' (best)' : '';
            return `<div style="margin:2px 0">
                <span style="display:inline-block;width:60px">offset ${{oi}}:</span>
                <span class="energy-bar" style="width:${{pct}}px;background:${{oi === d.downbeat_offset ? 'var(--green)' : 'var(--accent2)'}}"></span>
                <span style="margin-left:4px">${{s}}${{best}}</span>
            </div>`;
        }}).join('');

        return `<div class="detail" id="detail-${{i}}">
            <h3>${{d.track}}</h3>
            <div class="metric-grid">
                <div class="metric"><div class="value">${{d.bpm}}</div><div class="label">BPM</div></div>
                <div class="metric"><div class="value">${{d.bar_count}}</div><div class="label">Bars</div></div>
                <div class="metric"><div class="value ${{cvClass(d.bar_cv_original)}}">${{d.bar_cv_original}}%</div><div class="label">Bar CV (original)</div></div>
                <div class="metric"><div class="value">${{d.duration_s}}s</div><div class="label">Duration</div></div>
            </div>
            <div class="charts">
                <div class="chart-box">
                    <h4>Bar Durations</h4>
                    <canvas id="bars-${{i}}" width="400" height="120"></canvas>
                </div>
                <div class="chart-box">
                    <h4>Energy Timeline</h4>
                    <canvas id="energy-${{i}}" width="400" height="120"></canvas>
                </div>
                <div class="chart-box">
                    <h4>Downbeat Offset Scores</h4>
                    ${{offsetBars}}
                </div>
                <div class="chart-box">
                    <h4>Drift (per-segment BPM)</h4>
                    <div>${{d.drift.tempos.map((t, si) =>
                        `<span style="margin-right:8px">${{t}} BPM</span>`
                    ).join('')}}</div>
                    <div style="margin-top:4px;color:var(--text-dim)">
                        mean=${{d.drift.mean}}, std=${{d.drift.std}}, score=${{d.drift.drift_score}}
                    </div>
                </div>
            </div>
            <div class="chart-box" style="margin:12px 0">
                <h4>Beat Detection Comparison</h4>
                <table style="width:100%;font-size:12px">
                    <tr><th>Method</th><th>BPM</th><th>Bars</th><th>CV%</th><th>Downbeats</th></tr>
                    <tr>
                        <td>librosa (drums)</td>
                        <td>${{d.bpm}}</td>
                        <td>${{d.bar_count}}</td>
                        <td class="${{cvClass(d.bar_cv_original)}}">${{d.bar_cv_original}}%</td>
                        <td style="color:var(--text-dim)">stride-based</td>
                    </tr>
                    ${{d.bt_drums && d.bt_drums.cv >= 0 ? `<tr>
                        <td>beat-this (drums)</td>
                        <td>${{d.bt_drums.bpm}}</td>
                        <td>${{d.bt_drums.bars}}</td>
                        <td class="${{cvClass(d.bt_drums.cv)}}">${{d.bt_drums.cv}}%</td>
                        <td>${{d.bt_drums.downbeats}}</td>
                    </tr>` : ''}}
                    ${{d.bt_mix && d.bt_mix.cv >= 0 ? `<tr>
                        <td>beat-this (full mix)</td>
                        <td>${{d.bt_mix.bpm}}</td>
                        <td>${{d.bt_mix.bars}}</td>
                        <td class="${{cvClass(d.bt_mix.cv)}}">${{d.bt_mix.cv}}%</td>
                        <td>${{d.bt_mix.downbeats}}</td>
                    </tr>` : `<tr><td colspan="5" style="color:var(--text-dim)">${{d.has_source_audio === false ? 'beat-this not installed' : 'no source audio found'}}</td></tr>`}}
                    <tr style="border-top:2px solid var(--accent)">
                        <td><strong>Winner</strong></td>
                        <td colspan="4">${{winnerTag(d.bt_winner)}}</td>
                    </tr>
                </table>
            </div>
            <div class="chart-box" style="margin:12px 0">
                <h4>Deviant Bars (${{d.deviant_count}} bars &gt; 5% off median)</h4>
                <div class="bar-list">${{deviantRows || '<div style="color:var(--text-dim)">No deviant bars</div>'}}</div>
            </div>
            ${{d.correction_applied ? `<div style="padding:8px;background:rgba(74,222,128,0.1);border-radius:4px;margin:8px 0">
                Correction applied: ${{d.ghosts_removed > 0 ? d.ghosts_removed + ' ghost beats removed, ' : ''}}${{d.downbeat_offset > 0 ? 'offset ' + d.downbeat_offset + ', ' : ''}}CV ${{d.bar_cv_original}}% &rarr; ${{d.bar_cv_corrected}}%
            </div>` : ''}}
            <div class="player">
                <h4 style="margin-bottom:8px;color:var(--text-dim)">Audio Preview</h4>
                <audio controls preload="none" style="width:100%">
                    <source src="file://${{d.drums_path}}" type="audio/wav">
                </audio>
            </div>
        </div>`;
    }}).join('');
}}

function toggleDetail(idx) {{
    const el = document.getElementById('detail-' + idx);
    const wasOpen = el.classList.contains('open');
    // Close all
    document.querySelectorAll('.detail').forEach(d => d.classList.remove('open'));
    if (!wasOpen) {{
        el.classList.add('open');
        // Draw charts after opening
        setTimeout(() => drawCharts(idx), 50);
    }}
}}

function drawCharts(idx) {{
    const d = DATA.filter(x => !x.error)[idx];
    drawBarChart('bars-' + idx, d);
    drawEnergyChart('energy-' + idx, d);
}}

function drawBarChart(canvasId, d) {{
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.offsetWidth * 2;
    const h = canvas.height = 240;
    ctx.clearRect(0, 0, w, h);

    const bars = d.bar_durations;
    if (!bars.length) return;

    const median = d.median_bar_duration;
    const maxDur = Math.max(...bars.map(b => b.duration));
    const minDur = Math.min(...bars.map(b => b.duration));
    const range = maxDur - minDur || 1;
    const barW = Math.max(2, (w - 40) / bars.length);

    // Draw median line
    const medianY = h - 20 - ((median - minDur) / range) * (h - 40);
    ctx.strokeStyle = '#666';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(20, medianY);
    ctx.lineTo(w - 20, medianY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw bars
    bars.forEach((b, i) => {{
        const x = 20 + i * barW;
        const y = h - 20 - ((b.duration - minDur) / range) * (h - 40);
        const dev = Math.abs((b.duration - median) / median * 100);
        ctx.fillStyle = dev > 8 ? '#f87171' : dev > 5 ? '#fbbf24' : '#4ade80';
        ctx.fillRect(x, y, Math.max(1, barW - 1), h - 20 - y);
    }});

    // Labels
    ctx.fillStyle = '#888';
    ctx.font = '18px monospace';
    ctx.fillText(maxDur.toFixed(3) + 's', w - 80, 20);
    ctx.fillText(minDur.toFixed(3) + 's', w - 80, h - 5);
    ctx.fillText('median: ' + median.toFixed(3) + 's', 20, medianY - 5);
}}

function drawEnergyChart(canvasId, d) {{
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.offsetWidth * 2;
    const h = canvas.height = 240;
    ctx.clearRect(0, 0, w, h);

    const e = d.energy_timeline;
    if (!e.length) return;

    const maxE = Math.max(...e);
    const barW = (w - 20) / e.length;

    e.forEach((v, i) => {{
        const x = 10 + i * barW;
        const barH = (v / maxE) * (h - 20);
        ctx.fillStyle = v < maxE * 0.1 ? '#333' : v < maxE * 0.25 ? '#533483' : '#e94560';
        ctx.fillRect(x, h - 10 - barH, Math.max(1, barW - 1), barH);
    }});

    ctx.fillStyle = '#888';
    ctx.font = '18px monospace';
    ctx.fillText('0s', 10, h - 0);
    ctx.fillText(d.duration_s + 's', w - 60, h - 0);
}}

let sortCol = 3;
let sortAsc = false;

function sortTable(col) {{
    if (sortCol === col) sortAsc = !sortAsc;
    else {{ sortCol = col; sortAsc = col <= 1; }}

    const keys = ['track', 'bpm', 'bar_count', 'bar_cv_original', 'bt_drums.cv', 'bt_mix.cv', 'bt_winner', 'ghosts_removed', 'downbeat_offset', 'deviant_count', 'drift.drift_score', 'correction_applied'];
    const key = keys[col];

    const valid = DATA.filter(d => !d.error);
    valid.sort((a, b) => {{
        let va = key.includes('.') ? key.split('.').reduce((o, k) => o[k], a) : a[key];
        let vb = key.includes('.') ? key.split('.').reduce((o, k) => o[k], b) : b[key];
        if (typeof va === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        return sortAsc ? va - vb : vb - va;
    }});

    // Rebuild with sorted data
    const tbody = document.getElementById('table-body');
    const rows = Array.from(tbody.children);
    valid.forEach((d, i) => {{
        const origIdx = DATA.indexOf(d);
        rows.forEach(r => {{
            if (parseInt(r.dataset.idx) === origIdx) tbody.appendChild(r);
        }});
    }});
}}

function filterTable() {{
    const search = document.getElementById('search').value.toLowerCase();
    const status = document.getElementById('filter-status').value;

    document.querySelectorAll('#table-body tr').forEach(row => {{
        const idx = parseInt(row.dataset.idx);
        const d = DATA.filter(x => !x.error)[idx];
        if (!d) return;

        let show = true;
        if (search && !d.track.toLowerCase().includes(search)) show = false;
        if (status === 'corrected' && !d.correction_applied) show = false;
        if (status === 'issues' && d.bar_cv_original <= 3) show = false;
        if (status === 'clean' && d.bar_cv_original >= 1) show = false;

        row.style.display = show ? '' : 'none';
    }});
}}

window.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>"""

    output_path.write_text(html)
    print(f"Dashboard written to {output_path} ({output_path.stat().st_size:,} bytes)")


def main():
    ap = argparse.ArgumentParser(description="Generate beat analysis dashboard")
    ap.add_argument("--output", "-o", type=Path,
                    default=REPO_ROOT / "tools" / "beat_dashboard.html")
    ap.add_argument("--processed-dir", type=Path,
                    default=Path.home() / "stemforge" / "processed")
    ap.add_argument("--tracks", nargs="*", default=None,
                    help="Specific track names to analyze (default: all)")
    args = ap.parse_args()

    processed = args.processed_dir
    if not processed.exists():
        print(f"Processed directory not found: {processed}")
        return 1

    if args.tracks:
        track_dirs = [processed / t for t in args.tracks if (processed / t).is_dir()]
    else:
        track_dirs = sorted([d for d in processed.iterdir() if d.is_dir()])

    print(f"Analyzing {len(track_dirs)} tracks...")

    results = []
    for i, td in enumerate(track_dirs):
        name = td.name
        time_sig = 7 if "7_4" in name else 4
        print(f"  [{i+1}/{len(track_dirs)}] {name}...", end=" ", flush=True)
        result = analyze_track(td, time_sig=time_sig)
        if result:
            if "error" in result:
                print(f"ERROR: {result['error']}")
            else:
                cv = result["bar_cv_original"]
                status = "corrected" if result["correction_applied"] else "ok"
                print(f"BPM={result['bpm']}, bars={result['bar_count']}, CV={cv:.1f}% [{status}]")
            results.append(result)
        else:
            print("skipped (no drums.wav)")

    generate_html(results, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
