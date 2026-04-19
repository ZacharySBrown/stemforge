#!/usr/bin/env python3
"""validate_audio.py — Validate curated output quality via Gemini 2.5 Pro.

Sends each curated WAV to Gemini for multimodal audio analysis,
scores quality, and generates a report.

Usage:
    # Validate a curated manifest
    uv run python tools/validate_audio.py \
        ~/stemforge/processed/the_champ_original_version/curated/manifest.json

    # Validate specific stems only
    uv run python tools/validate_audio.py manifest.json --stems drums bass

    # Dry run (show what would be validated without calling API)
    uv run python tools/validate_audio.py manifest.json --dry-run

Requires: GEMINI_API_KEY in .env or environment
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Load .env
env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


def validate_manifest(
    manifest_path: Path,
    stems_filter: list[str] | None = None,
    dry_run: bool = False,
    max_per_stem: int = 4,
) -> dict:
    """Validate curated samples via Gemini 2.5 Pro."""
    try:
        from google import genai
    except ImportError:
        print("ERROR: pip install google-genai")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set (check .env)")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    model = "gemini-2.5-pro-preview-05-06"

    manifest = json.loads(manifest_path.read_text())
    track_name = manifest.get("track", "unknown")
    bpm = manifest.get("bpm", 120)

    print(f"Validating: {track_name} ({bpm:.0f} BPM)")
    print(f"Model: {model}")
    print()

    results = {"track": track_name, "bpm": bpm, "stems": {}}

    for stem_name, stem_data in manifest.get("stems", {}).items():
        if stems_filter and stem_name not in stems_filter:
            continue

        print(f"=== {stem_name} ===")

        # Collect files to validate
        files_to_check = []

        if isinstance(stem_data, dict):
            loops = stem_data.get("loops", [])
            oneshots = stem_data.get("oneshots", [])
            for item in loops[:max_per_stem]:
                files_to_check.append(("loop", item))
            for item in oneshots[:max_per_stem]:
                files_to_check.append(("oneshot", item))
        elif isinstance(stem_data, list):
            for item in stem_data[:max_per_stem]:
                files_to_check.append(("loop", item))

        stem_results = []

        for item_type, item in files_to_check:
            file_path = Path(item.get("file", ""))
            if not file_path.exists():
                print(f"  SKIP: {file_path.name} (file not found)")
                continue

            classification = item.get("classification", "")
            phrase_bars = item.get("phrase_bars", 1)

            if dry_run:
                print(f"  DRY RUN: {file_path.name} ({item_type})")
                continue

            # Build prompt
            if item_type == "loop":
                prompt = (
                    f"Listen to this audio file. It was extracted from the {stem_name} stem "
                    f"of a song at {bpm:.0f} BPM. It should be a {phrase_bars}-bar musical loop.\n\n"
                    f"1. What do you hear? Describe the musical content in 1-2 sentences.\n"
                    f"2. Does this sound like a {stem_name} stem? (yes/no/partial)\n"
                    f"3. Is it mostly silence? (yes/no, estimate % silent)\n"
                    f"4. Would this loop well? (yes/no)\n"
                    f"5. Quality score 1-5: (1=garbage/noise, 3=usable, 5=excellent musical content)\n\n"
                    f"Respond in this exact JSON format:\n"
                    f'{{"description": "...", "correct_stem": "yes/no/partial", '
                    f'"mostly_silent": "yes/no", "silent_pct": 0, "loops_well": "yes/no", '
                    f'"quality_score": 3}}'
                )
            else:
                prompt = (
                    f"Listen to this audio file. It was extracted as a one-shot from the {stem_name} stem. "
                    f"It is classified as: {classification or 'unclassified'}.\n\n"
                    f"1. What do you hear? Describe the sound in 1 sentence.\n"
                    f"2. Is this a single isolated hit, or does it contain multiple events?\n"
                    f"3. Does the classification '{classification}' match what you hear? "
                    f"(yes/no, what is it actually?)\n"
                    f"4. Is the duration appropriate? (too short / good / too long)\n"
                    f"5. Quality score 1-5: (1=noise/artifact, 3=usable hit, 5=clean isolated hit)\n\n"
                    f"Respond in this exact JSON format:\n"
                    f'{{"description": "...", "single_hit": "yes/no", '
                    f'"classification_correct": "yes/no", "actual_classification": "...", '
                    f'"duration_appropriate": "good/too short/too long", "quality_score": 3}}'
                )

            print(f"  Checking: {file_path.name} ({item_type})...", end=" ", flush=True)

            try:
                # Upload file to Gemini
                uploaded = client.files.upload(file=file_path)

                # Wait for processing
                while uploaded.state.name == "PROCESSING":
                    time.sleep(1)
                    uploaded = client.files.get(name=uploaded.name)

                response = client.models.generate_content(
                    model=model,
                    contents=[uploaded, prompt],
                )

                # Parse response
                text = response.text.strip()
                # Extract JSON from response (may be wrapped in markdown)
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()

                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    result = {"raw_response": text, "quality_score": 0}

                result["file"] = file_path.name
                result["type"] = item_type
                result["classification"] = classification
                score = result.get("quality_score", 0)
                print(f"score={score}/5 — {result.get('description', '')[:60]}")

                stem_results.append(result)

                # Clean up uploaded file
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass

                # Rate limiting
                time.sleep(1)

            except Exception as e:
                print(f"ERROR: {e}")
                stem_results.append({
                    "file": file_path.name, "type": item_type,
                    "error": str(e), "quality_score": 0,
                })

        results["stems"][stem_name] = stem_results

        if stem_results:
            scores = [r.get("quality_score", 0) for r in stem_results if r.get("quality_score")]
            avg = sum(scores) / len(scores) if scores else 0
            print(f"  Average: {avg:.1f}/5 ({len(scores)} samples)\n")

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_scores = []
    for stem_name, stem_results in results["stems"].items():
        scores = [r.get("quality_score", 0) for r in stem_results if r.get("quality_score")]
        if scores:
            avg = sum(scores) / len(scores)
            all_scores.extend(scores)
            status = "PASS" if avg >= 3.0 else "FAIL"
            print(f"  {stem_name:8s}: {avg:.1f}/5 ({len(scores)} samples) [{status}]")

    if all_scores:
        overall = sum(all_scores) / len(all_scores)
        overall_status = "PASS" if overall >= 3.0 else "FAIL"
        print(f"\n  OVERALL: {overall:.1f}/5 [{overall_status}]")

    # Write report
    report_path = manifest_path.parent / "quality_report.json"
    report_path.write_text(json.dumps(results, indent=2))
    print(f"\n  Report: {report_path}")

    return results


def main():
    ap = argparse.ArgumentParser(description="Validate curated audio via Gemini 2.5 Pro")
    ap.add_argument("manifest", type=Path, help="Path to curated manifest.json")
    ap.add_argument("--stems", nargs="+", default=None, help="Only validate these stems")
    ap.add_argument("--dry-run", action="store_true", help="Show plan without calling API")
    ap.add_argument("--max-per-stem", type=int, default=4, help="Max samples to check per stem per type")
    args = ap.parse_args()

    validate_manifest(args.manifest, stems_filter=args.stems,
                     dry_run=args.dry_run, max_per_stem=args.max_per_stem)


if __name__ == "__main__":
    main()
