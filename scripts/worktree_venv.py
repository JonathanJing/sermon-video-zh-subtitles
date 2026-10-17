"""Transition facade for tools.development.worktree_venv.

Keep the existing import path and script command during the directory move.
"""
from pathlib import Path
import sys

if __package__ in {None, ""}:  # python3 scripts/worktree_venv.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.development import worktree_venv as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
