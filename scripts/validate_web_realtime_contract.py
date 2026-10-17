"""Transition facade for tools.ops.validate_web_realtime_contract.

Keep the existing import path and script command during the directory move.
"""
from pathlib import Path
import sys

if __package__ in {None, ""}:  # python3 scripts/validate_web_realtime_contract.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import validate_web_realtime_contract as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
