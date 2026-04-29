#!/usr/bin/env python3
"""
generate_static_onnx.py

Converts htdemucs_ft_fused.onnx to a static-shape variant that CoreML EP
and CUDA EP can accept. Fixes the dynamic time_out_stacked output shape
that caused CoreML to reject the graph.

Usage:
    python3 generate_static_onnx.py
    python3 generate_static_onnx.py --input /path/to/fused.onnx --output /path/to/static.onnx
    python3 generate_static_onnx.py --save-to-repo
"""

import argparse
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_INPUT = os.path.expanduser(
    "~/Library/Application Support/StemForge/models/htdemucs_ft/htdemucs_ft_fused.onnx"
)
DEFAULT_OUTPUT = os.path.expanduser(
    "~/Library/Application Support/StemForge/models/htdemucs_ft/htdemucs_ft_fused_static.onnx"
)
REPO_OUTPUT = Path(__file__).parent / "v0/build/models/htdemucs_ft/htdemucs_ft_fused_static.onnx"

# Fixed output shape for time_out_stacked.
# [4 heads, 2 channels (stereo), 343980 samples (= ~7.8s @ 44.1kHz)]
TIME_OUT_SHAPE = [4, 2, 343980]


def main():
    parser = argparse.ArgumentParser(description="Generate static-shape ONNX from fused htdemucs_ft")
    parser.add_argument("--input",  default=DEFAULT_INPUT,  help="Path to htdemucs_ft_fused.onnx")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to write the static .onnx")
    parser.add_argument("--save-to-repo", action="store_true",
                        help="Also copy the result into v0/build/models/htdemucs_ft/ (repo path)")
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Check onnx is available
    # -----------------------------------------------------------------------
    try:
        import onnx
        from onnx import shape_inference
    except ImportError:
        print("ERROR: onnx package not found. Install it with:")
        print("  pip install onnx")
        sys.exit(1)

    input_path  = Path(args.input)
    output_path = Path(args.output)

    # -----------------------------------------------------------------------
    # Validate input
    # -----------------------------------------------------------------------
    if not input_path.exists():
        print(f"ERROR: Input file not found:\n  {input_path}")
        print("\nAvailable .onnx files under ~/Library/Application Support/StemForge/:")
        base = Path.home() / "Library/Application Support/StemForge"
        for f in sorted(base.rglob("*.onnx")):
            print(f"  {f}")
        sys.exit(1)

    print(f"Input:  {input_path}  ({input_path.stat().st_size / 1e6:.1f} MB)")
    print(f"Output: {output_path}")
    print()

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------
    print("Loading model...")
    m = onnx.load(str(input_path))
    print(f"  Nodes: {len(m.graph.node)}")
    print(f"  Inputs:  {[i.name for i in m.graph.input]}")
    print(f"  Outputs: {[o.name for o in m.graph.output]}")
    print()

    # -----------------------------------------------------------------------
    # Print current output shapes (before fix)
    # -----------------------------------------------------------------------
    print("Current output shapes (before fix):")
    for output in m.graph.output:
        shape = []
        for d in output.type.tensor_type.shape.dim:
            if d.dim_value > 0:
                shape.append(d.dim_value)
            else:
                shape.append(f"?{d.dim_param}" if d.dim_param else "?")
        print(f"  {output.name}: {shape}")
    print()

    # -----------------------------------------------------------------------
    # Fix dynamic output shape on time_out_stacked
    # -----------------------------------------------------------------------
    fixed = False
    for output in m.graph.output:
        if output.name == "time_out_stacked":
            output.type.tensor_type.shape.ClearField("dim")
            for d in TIME_OUT_SHAPE:
                dim = output.type.tensor_type.shape.dim.add()
                dim.dim_value = d
            fixed = True
            print(f"Fixed time_out_stacked shape → {TIME_OUT_SHAPE}")
            break

    if not fixed:
        print("WARNING: time_out_stacked output not found — model may already be static,")
        print("         or the output name has changed. Proceeding anyway.")
    print()

    # -----------------------------------------------------------------------
    # Shape inference + validation
    # -----------------------------------------------------------------------
    print("Running shape inference...")
    m = shape_inference.infer_shapes(m)

    print("Validating model...")
    onnx.checker.check_model(m)
    print("  Validation passed.")
    print()

    # -----------------------------------------------------------------------
    # Print final output shapes (after fix)
    # -----------------------------------------------------------------------
    print("Final output shapes (after fix):")
    for output in m.graph.output:
        shape = []
        for d in output.type.tensor_type.shape.dim:
            if d.dim_value > 0:
                shape.append(d.dim_value)
            else:
                shape.append(f"?{d.dim_param}" if d.dim_param else "?")
        print(f"  {output.name}: {shape}")
    print()

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Saving static model to:\n  {output_path}")
    onnx.save(m, str(output_path))
    print(f"  Saved ({output_path.stat().st_size / 1e6:.1f} MB)")
    print()

    # -----------------------------------------------------------------------
    # Optionally also copy into the repo
    # -----------------------------------------------------------------------
    if args.save_to_repo:
        REPO_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(str(output_path), str(REPO_OUTPUT))
        print(f"Also saved to repo:\n  {REPO_OUTPUT}")
        print()

    # -----------------------------------------------------------------------
    # Print next steps
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("Done. Next steps:")
    print()
    print("1. Upload to Modal volume:")
    print("   modal volume create stemforge-models  # skip if already exists")
    print(f"   modal volume put stemforge-models \\")
    print(f'     "{output_path}" \\')
    print(f"     /htdemucs_ft_fused_static.onnx")
    print()
    print("2. Run the CUDA compatibility test:")
    print("   modal run test_cuda_compat.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
