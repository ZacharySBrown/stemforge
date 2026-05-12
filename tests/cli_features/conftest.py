"""Worktree-aware sys.path fix for the cli_features test suite.

The repo's editable install (``__editable__.stemforge-0.2.0.pth``) points
at the *main* repo path, so when these tests run inside a git worktree
the package imported by name (``stemforge``) is from the wrong path. We
prepend the worktree repo root to ``sys.path`` AND evict any cached
``stemforge`` modules so subsequent imports load the worktree's source.

Scope this fix narrowly: the eviction lives in this conftest so it
applies only to tests under ``tests/cli_features/``. The full-suite
test runner imports ``test_audit.py`` (which keeps a module-level
reference to ``stemforge.audit``) before reaching us; evicting from a
sibling top-level test file invalidates that reference and breaks
``importlib.reload`` in test_audit's fixtures.

Doing the eviction here, in a session-scoped autouse fixture that
re-imports ``stemforge.audit`` after the eviction, leaves the rest of
the suite undisturbed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Evict cached stemforge modules so the next import loads from this
# worktree's source. We DO NOT evict modules that other test files in
# the suite hold module-level references to (``stemforge.audit`` is the
# notable one — test_audit.py imports it at module scope and reloads it
# in a fixture; evicting + not re-importing breaks the reload).
_PRESERVE = {"stemforge.audit"}
_preserved: dict[str, object] = {}
for _mod_name in list(sys.modules):
    if _mod_name == "stemforge" or _mod_name.startswith("stemforge."):
        if _mod_name in _PRESERVE:
            _preserved[_mod_name] = sys.modules[_mod_name]
        del sys.modules[_mod_name]

# Re-import the preserved modules so any other test file's
# ``import stemforge.audit as audit_mod`` reference still resolves.
import importlib  # noqa: E402

for _mod_name in _preserved:
    importlib.import_module(_mod_name)
