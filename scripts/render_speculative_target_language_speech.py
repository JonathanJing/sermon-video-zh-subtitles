"""Transition facade: speculative audio preview lives in tongxing_production.audio.speculative.

Both import paths name one module object; the old CLI still dispatches main().
"""
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT, _ROOT / "packages/production/src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from scripts import tongxing_host  # noqa: F401  binds audio ports
from tongxing_production.audio import speculative as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
