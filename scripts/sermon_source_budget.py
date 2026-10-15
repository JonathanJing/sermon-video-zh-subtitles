"""Transition facade: the implementation lives in tongxing_production.source.budget.

Both import paths name one module object, so attribute patches apply to both.
Remove once no caller imports the old path.
"""
import sys

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import budget as _implementation

sys.modules[__name__] = _implementation
