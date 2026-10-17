"""Transition facade: speculative audio preview lives in tongxing_production.audio.speculative.

Both import paths name one module object; the old CLI still dispatches main().
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds audio ports
except ModuleNotFoundError:  # direct execution from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.audio import speculative as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
