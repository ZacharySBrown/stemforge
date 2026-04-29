#!/usr/bin/env python3
"""
generate_static_onnx.py

Converts htdemucs_ft_fused.onnx to a static-shape variant that CoreML EP
and CUDA EP can accept. Fixes the dynamic time_out_stacked output shape
that caused CoreML to reject the graph.

Default output is htdemucs_ft_fused_static.onnx in the directory you run
the script from. So just cd to ~/stemforge/batch and run it.

Usage:
    cd ~/stemforge/batch
    python3 generate_static_onnx.py

    python3 generate_static_onnx.py --input /path/to/fused.onnx
    python3 generate_static_onnx.py --output /custom/path/static.onnx
"""

import argparse
import os
import sys
from pathlib import Path

DEFAULT_INPUT = os.path.expanduser(
    "~/Library/Application Support/StemForge/models/htdemucs_ft/htdemucs_ft_fused.onnx"
)

# Fixed output shape: [4 heads, 2 channels stereo, 343980 samples ~7.8s @ 44.1kHz]
TIME_OUT_SHAPE = [4, 2, 343980]


def main():
    default_output = str(Path.cwd() / "htdemucs_ft_fused_static.onnx")

    parser = argparse.ArgumentParser(
        description="Generate static-shape ONNX from fused htdemucs_ft"
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help="Path to htdemucs_ft_fused.onnx",
    )
    parser.add_argument(
        "--output",
        default=default_output,
        help="Output path (default: <cwd>/htdemucs_ft_fused_static.onnx)",
    )
    args = parser.parse_args()

    try:
        import onnx
        from onnx import shape_inference
    except ImportError:
        print("ERROR: onnx not found. Install with: pip install onnx")
        sys.exit(1)

    input_path  = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"ERROR: Input file not found:\n  {input_path}")
        print("\nSearching for .onnx files under ~/Library/Application Support/StemForge/:")
        base = Path.home() / "Library/Application Support/StemForge"
        for f in sorted(base.rglob("*.onnx")):
            print(f"  {f}")
        sys.exit(1)

    print(f"Input:  {input_path}  ({input_path.stat().st_size / 1e6:.1f} MB)")
    print(f"Output: {output_path}\n")

    print("Loading model...")
    m = onnx.load(str(input_path))
    print(f"  Nodes:   {len(m.graph.node)}")
    print(f"  Inputs:  {[i.name for i in m.graph.input]}")
    print(f"  Outputs: {[o.name for o in m.graph.output]}\n")

    print("Current output shapes (before fix):")
    for output in m.graph.output:
        shape = []
        for d in output.type.tensor_type.shape.dim:
            shape.append(d.dim_value if d.dim_value > 0 else f"?{d.dim_param or ''}")
        print(f"  {output.name}: {shape}")
    print()

    fixed = False
    for output in m.graph.output:
        if output.name == "time_out_stacked":
            output.type.tensor_type.shape.ClearField("dim")
            for d in TIME_OUT_SHAPE:
                dim = output.type.tensor_type.shape.dim.add()
                dim.dim_value = d
            fixed = True
            print(f"Fixed time_out_stacked → {TIME_OUT_SHAPE}")
            break

    if not fixed:
        print("WARNING: time_out_stacked not found — may already be static.")
    print()

    print("Running shape inference...")
    m = shape_inference.infer_shapes(m)

    print("Validating model...")
    onnx.checker.check_model(m)
    print("  Validation passed.\n")

    print("Final output shapes (after fix):")
    for output in m.graph.output:
        shape = []
        for d in output.type.tensor_type.shape.dim:
            shape.append(d.dim_value if d.dim_value > 0 else f"?{d.dim_param or ''}")
        print(f"  {output.name}: {shape}")
    print()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Saving to:\n  {output_path}")
    onnx.save(m, str(output_path))
    print(f"  Done ({output_path.stat().st_size / 1e6:.1f} MB)\n")

    print("=" * 60)
    print("Next steps:\n")
    print("  modal volume create stemforge-models  # skip if already exists")
    print(f"  modal volume put stemforge-models \\")
    print(f'    "{output_path}" \\')
    print( "    /htdemucs_ft_fused_static.onnx\n")
    print("  modal run test_cuda_compat.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
