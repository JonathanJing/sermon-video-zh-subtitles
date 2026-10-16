"""Transition facade: the implementation lives in tongxing_production.contracts.pipeline_definition.

Both import paths name one module object, so attribute patches apply to both.
Remove once no caller imports the old path.
"""
import sys

from tongxing_production.contracts import pipeline_definition as _implementation

sys.modules[__name__] = _implementation
