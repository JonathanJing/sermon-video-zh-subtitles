"""Transition facade: the implementation lives in tongxing_production.audio.strict_preparation.

Both import paths name one module object, so attribute patches apply to both.
The diagnostic chain still imports the old path. Remove once no caller imports it.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # imported by bare name from a script run directly in scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.audio import strict_preparation as _implementation

sys.modules[__name__] = _implementation
