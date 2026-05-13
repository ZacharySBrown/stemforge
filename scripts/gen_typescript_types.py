"""Generate TypeScript type definitions from the configurator Pydantic schemas.

Run as::

    uv run python scripts/gen_typescript_types.py

Writes ``web/configurator/src/lib/api-types.generated.ts``.

Output is deterministic: schemas are sorted by name, properties within
each schema are sorted, union members are sorted. Re-running with no
schema change must produce an identical file (this is enforced by
``.github/workflows/ci-types-drift.yml``).

We hand-roll the JSON-schema → TS conversion instead of pulling in
``datamodel-code-generator`` because (a) the schemas are small and
finitely shaped, (b) we control the input (we generate the JSON schema
in ``stemforge.configurator.schemas.export``), and (c) avoiding the
extra dep keeps the dev install lean.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Make sure we can import stemforge regardless of CWD.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from stemforge.configurator.schemas.export import (  # noqa: E402
    export_all_json_schemas,
)

OUTPUT_PATH = (
    _REPO_ROOT / "web" / "configurator" / "src" / "lib" / "api-types.generated.ts"
)

BANNER = (
    "// AUTO-GENERATED — do not edit. Run "
    "`uv run python scripts/gen_typescript_types.py` to regenerate.\n"
    "// Source of truth: stemforge/configurator/schemas/\n"
)


# ---------------------------------------------------------------------------
# JSON-schema → TypeScript conversion
# ---------------------------------------------------------------------------


def _ref_name(ref: str) -> str:
    """``#/$defs/Pad`` → ``Pad``."""
    return ref.rsplit("/", 1)[-1]


def _schema_to_ts(schema: dict[str, Any], known_names: set[str]) -> str:
    """Convert a single JSON-schema node to a TypeScript type expression."""

    # $ref → named type
    if "$ref" in schema:
        return _ref_name(schema["$ref"])

    # const literal (e.g. ``schema_version: 1``, ``type: "deck"``)
    if "const" in schema:
        const = schema["const"]
        return _literal_to_ts(const)

    # enum
    if "enum" in schema:
        members = [_literal_to_ts(v) for v in schema["enum"]]
        return " | ".join(sorted(set(members)))

    # anyOf — typically Pydantic's encoding of ``X | None`` or unions
    if "anyOf" in schema:
        members = [_schema_to_ts(s, known_names) for s in schema["anyOf"]]
        # Deduplicate but preserve null at the end for readability.
        seen: list[str] = []
        for m in members:
            if m not in seen:
                seen.append(m)
        return " | ".join(seen)

    # oneOf — treat like anyOf for our purposes
    if "oneOf" in schema:
        members = [_schema_to_ts(s, known_names) for s in schema["oneOf"]]
        seen2: list[str] = []
        for m in members:
            if m not in seen2:
                seen2.append(m)
        return " | ".join(seen2)

    json_type = schema.get("type")
    if json_type == "string":
        # ``format: date-time`` → string (we render ISO timestamps as strings).
        return "string"
    if json_type == "integer" or json_type == "number":
        return "number"
    if json_type == "boolean":
        return "boolean"
    if json_type == "null":
        return "null"
    if json_type == "array":
        # Pydantic 2 emits tuples as ``prefixItems`` (draft 2020-12).
        prefix = schema.get("prefixItems")
        if isinstance(prefix, list):
            elems = [_schema_to_ts(s, known_names) for s in prefix]
            return "[" + ", ".join(elems) + "]"
        items = schema.get("items")
        if isinstance(items, dict):
            inner = _schema_to_ts(items, known_names)
            return f"Array<{inner}>"
        if isinstance(items, list):
            # Older draft fallback.
            elems = [_schema_to_ts(s, known_names) for s in items]
            return "[" + ", ".join(elems) + "]"
        return "Array<unknown>"
    if json_type == "object":
        ap = schema.get("additionalProperties")
        if isinstance(ap, dict):
            value_t = _schema_to_ts(ap, known_names)
            return f"Record<string, {value_t}>"
        if ap is True:
            return "Record<string, unknown>"
        # Inline object literal with named properties — rare in our schemas.
        props = schema.get("properties", {})
        if props:
            parts = []
            required = set(schema.get("required", []))
            for k in sorted(props.keys()):
                opt = "" if k in required else "?"
                parts.append(f"{k}{opt}: {_schema_to_ts(props[k], known_names)}")
            return "{ " + "; ".join(parts) + " }"
        return "Record<string, unknown>"

    # Pydantic's ``prefixItems`` (tuple) — top-level shape.
    if "prefixItems" in schema:
        elems = [_schema_to_ts(s, known_names) for s in schema["prefixItems"]]
        return "[" + ", ".join(elems) + "]"

    return "unknown"


def _literal_to_ts(value: Any) -> str:
    if isinstance(value, str):
        # Use double-quoted strings to match TS prettier defaults in this repo.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return "unknown"


def _render_model(name: str, schema: dict[str, Any], known_names: set[str]) -> str:
    """Render a top-level model as a TypeScript interface."""

    description = schema.get("description", "").strip()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    lines: list[str] = []
    if description:
        # Convert to /** */ JSDoc block.
        doc_lines = description.split("\n")
        lines.append("/**")
        for line in doc_lines:
            lines.append(f" * {line}".rstrip())
        lines.append(" */")

    lines.append(f"export interface {name} {{")

    for key in sorted(props.keys()):
        prop = props[key]
        prop_desc = prop.get("description", "").strip()
        if prop_desc:
            lines.append(f"  /** {prop_desc} */")
        ts_type = _schema_to_ts(prop, known_names)
        opt = "" if key in required else "?"
        lines.append(f"  {key}{opt}: {ts_type};")

    lines.append("}")
    return "\n".join(lines)


def render_typescript(schemas: dict[str, dict[str, Any]]) -> str:
    """Render the full TypeScript output as a single string."""

    known_names = set(schemas.keys())
    blocks = [BANNER]
    for name in sorted(schemas.keys()):
        blocks.append(_render_model(name, schemas[name], known_names))
    return "\n\n".join(blocks).rstrip() + "\n"


def main() -> None:
    schemas = export_all_json_schemas()
    output = render_typescript(schemas)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH.relative_to(_REPO_ROOT)} ({len(output)} bytes)")


if __name__ == "__main__":
    main()
