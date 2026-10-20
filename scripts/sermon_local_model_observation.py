"""Transition facade: the implementation lives in tongxing_production.observability.local_model_observation.

Both import paths name one module object, so attribute patches apply to both.
The host, the observability trace exporter and the diagnostic chain still import
the old path. Remove once no caller imports it.
"""
import sys

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.observability import local_model_observation as _implementation

sys.modules[__name__] = _implementation
