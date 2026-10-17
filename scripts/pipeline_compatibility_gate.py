"""Transition facade for tools.development.pipeline_compatibility_gate.

Keep the existing import path and both script and module CLI entry points.
"""
from pathlib import Path
import sys

if __package__ in {None, ""}:  # python scripts/pipeline_compatibility_gate.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.development import pipeline_compatibility_gate as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
