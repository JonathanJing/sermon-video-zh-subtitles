"""Transition facade for tools.development.ci_change_scope.

Keep the existing import path and direct/module CLI entry points for CI.
"""

from pathlib import Path
import sys

if __package__ in {None, ""}:  # python scripts/ci_change_scope.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.development import ci_change_scope as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
