"""Pytest config: makes the strip's builder importable as a bare module."""

from __future__ import annotations

import sys
from pathlib import Path

# The strip's source lives one level up. The directory name contains hyphens,
# so we can't import it as a normal Python package — add it to sys.path so
# `from builder import build_patcher` works inside test files.
HERE = Path(__file__).resolve().parent
SRC = HERE.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
