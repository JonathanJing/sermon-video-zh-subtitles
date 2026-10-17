"""Transition facade for the CUV evidence preflight implementation.

The legacy and package import paths refer to the same module object.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds this checkout's package
except ModuleNotFoundError:  # imported by bare name from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.text import cuv_preflight as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
