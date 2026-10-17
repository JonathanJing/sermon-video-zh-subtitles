"""Transition facade for the Source failure receipt implementation.

Both import paths name one module object so old diagnostic callers and patches
keep the same strict receipt behavior and execution-code identity.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # imported by bare name from a script run directly in scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.source import failure as _implementation

sys.modules[__name__] = _implementation
