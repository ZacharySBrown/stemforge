"""stemforge.exporters — Format stems/slices for hardware samplers."""

from enum import Enum


class ExportTarget(Enum):
    EP133 = "ep133"
    CHOMPI = "chompi"


class ExportWorkflow(Enum):
    COMPOSE = "compose"   # deep: all slices from one track
    PERFORM = "perform"   # wide: curated across multiple tracks
