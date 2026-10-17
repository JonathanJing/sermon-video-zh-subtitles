"""Transition facade: implementation lives in tongxing_production.review.seeded_errors.

Both import paths share one module object, so legacy patches still apply.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds package ports
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.review import seeded_errors as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
