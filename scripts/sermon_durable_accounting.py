"""Transition facade: the implementation lives in tongxing_production.observability.durable.

Both import paths name one module object, so attribute patches apply to both.
Remove once no caller imports the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # imported by bare name from a script run directly in scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.observability import durable as _implementation

sys.modules[__name__] = _implementation
