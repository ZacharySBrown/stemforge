#!/usr/bin/env python3
"""Validate a stream of NDJSON lines on stdin against
v0/interfaces/ndjson.schema.json.

Used by the Track A self-test:
    ./stemforge-native split foo.wav --json-events \
        | jq -c 'select(.event)' \
        | python v0/tests/validate-ndjson.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover
    print("jsonschema not installed — run `uv pip install jsonschema`",
          file=sys.stderr)
    sys.exit(2)

SCHEMA_PATH = (Path(__file__).resolve().parents[1]
               / "interfaces" / "ndjson.schema.json")


def main() -> int:
    with SCHEMA_PATH.open() as f:
        schema = json.load(f)
    validator = jsonschema.Draft7Validator(schema)

    ok = 0
    bad = 0
    for i, line in enumerate(sys.stdin, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"line {i}: not JSON: {e}", file=sys.stderr)
            bad += 1
            continue
        errors = list(validator.iter_errors(obj))
        if errors:
            print(f"line {i}: schema violation:", file=sys.stderr)
            for e in errors:
                print(f"  {e.message}", file=sys.stderr)
            bad += 1
        else:
            ok += 1
    print(f"{ok} valid, {bad} invalid", file=sys.stderr)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
