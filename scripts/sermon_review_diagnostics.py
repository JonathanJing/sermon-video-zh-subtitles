"""Transition facade: strict L2 structural diagnostics live in the text package.

Both import paths name one module object, so existing callers and patches keep
their behavior while the implementation belongs to Layer 2.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # imported by bare name from a script run directly in scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.text import review_diagnostics as _implementation

sys.modules[__name__] = _implementation
