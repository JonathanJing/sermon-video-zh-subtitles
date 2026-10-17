"""Compatibility entry point for tools/ops/sermon_unified_preflight.py.

Keep the old CLI and module object for callers that patch imported dependencies.
"""

from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import sermon_unified_preflight as _implementation

if __name__ == '__main__':
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
