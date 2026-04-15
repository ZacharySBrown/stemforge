"""Pytest shim: als-builder directory contains a dash, so it can't be
imported as a package. Add the parent dir to sys.path so tests can
`from builder import …` and `from colors import …`.
"""

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_ALS_BUILDER_DIR = _THIS_DIR.parent
if str(_ALS_BUILDER_DIR) not in sys.path:
    sys.path.insert(0, str(_ALS_BUILDER_DIR))
