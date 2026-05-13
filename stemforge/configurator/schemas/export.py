"""JSON schema export utility.

Run as a module to dump every Pydantic schema in this package as a single
JSON object on stdout::

    python -m stemforge.configurator.schemas.export > schemas.json

This is the upstream half of the TypeScript codegen pipeline; the
downstream half lives in ``scripts/gen_typescript_types.py``.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import BaseModel

from . import (
    ArrangementChunk,
    ArrangementManifest,
    ClipSettings,
    Curation,
    ForgeClip,
    ForgeManifest,
    Group,
    LastBounce,
    LastExport,
    Pad,
    PadSource,
    ReferencedForge,
    StemforgeState,
    Target,
)

# Stable export order. Same order ⇒ stable diff under ``ci-types-drift``.
_MODELS: list[type[BaseModel]] = [
    ArrangementChunk,
    ArrangementManifest,
    ClipSettings,
    Curation,
    ForgeClip,
    ForgeManifest,
    Group,
    LastBounce,
    LastExport,
    Pad,
    PadSource,
    ReferencedForge,
    StemforgeState,
    Target,
]


def export_all_json_schemas() -> dict[str, dict[str, Any]]:
    """Return ``{ModelName: json_schema_dict}`` for every configurator schema.

    Each returned schema has a stable ``$id`` of the form
    ``"stemforge://configurator/<ModelName>"`` so downstream tooling can
    reference them by name.
    """

    result: dict[str, dict[str, Any]] = {}
    for model in sorted(_MODELS, key=lambda m: m.__name__):
        schema = model.model_json_schema()
        schema["$id"] = f"stemforge://configurator/{model.__name__}"
        result[model.__name__] = schema
    return result


def _main() -> None:
    schemas = export_all_json_schemas()
    json.dump(schemas, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    _main()
