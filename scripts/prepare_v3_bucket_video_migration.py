"""Compatibility entry point for tools.ops.prepare_v3_bucket_video_migration.

Keep the old direct and module CLI and import path.
"""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import prepare_v3_bucket_video_migration as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
