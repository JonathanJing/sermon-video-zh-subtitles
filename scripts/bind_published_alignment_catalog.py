"""Transition facade for the published alignment catalog binder.

The import and CLI paths use the same package implementation.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds package ports
except ModuleNotFoundError:  # direct execution from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.delivery import published_alignment_catalog as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
