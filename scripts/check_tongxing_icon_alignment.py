"""Transition facade for tools.development.check_tongxing_icon_alignment.

Keep the CI and documented script command during the directory move.
"""
from pathlib import Path
import sys

if __package__ in {None, ""}:  # python scripts/check_tongxing_icon_alignment.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.development import check_tongxing_icon_alignment as _implementation

if __name__ == "__main__":
    _implementation.check()
sys.modules[__name__] = _implementation
