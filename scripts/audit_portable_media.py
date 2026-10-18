"""Compatibility entry point for tools.ops.audit_portable_media.

Keep the existing import path and direct/module CLI commands.
"""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import audit_portable_media as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
