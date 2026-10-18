"""Transition facade for tools.ops.import_openai_costs.

Keep the existing import path and ``python -m scripts.import_openai_costs`` command.
"""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import import_openai_costs as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
