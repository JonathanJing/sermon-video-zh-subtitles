"""Transition facade: the Layer 3 stage lives in tongxing_production.audio.unified_stage.

Both import paths name one module object so legacy patches and callers stay bound.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds audio ports
except ModuleNotFoundError:  # direct import from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.audio import unified_stage as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
