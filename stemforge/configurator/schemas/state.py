"""Server-side runtime state (``~/stemforge/.stemforge_state.json``).

Per spec §2.4. Persists the active curation per ``.als`` so the popup can
re-attach to "the right curation" when Live reopens a known project.

This is the **only** persistent runtime state outside of curation files
themselves. Small, server-owned, atomic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StemforgeState(BaseModel):
    """Server-side runtime state file.

    Keyed by the absolute path of a Live ``.als`` project file.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    schema_version: Literal[1] = 1
    active_curations: dict[str, str] = Field(
        default_factory=dict,
        description="Map of .als absolute path → active curation name",
    )
    last_known_port: int | None = Field(
        None,
        ge=1,
        le=65535,
        description="Most recent server port (mirrors .configurator_port)",
    )
    last_seen_at: datetime | None = None
