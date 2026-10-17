"""Transition facade for tools.development.verify_fingerprint_browser_cache.

Keep the documented script command while the browser smoke lives in tools.
"""
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.development import verify_fingerprint_browser_cache as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
