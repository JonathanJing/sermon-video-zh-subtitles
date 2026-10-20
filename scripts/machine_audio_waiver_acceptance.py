"""Transition facade: implementation lives in tongxing_production.review.audio_waiver_acceptance.

Both import paths share one module object, so legacy patches still apply.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds package ports
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.review import audio_waiver_acceptance as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
