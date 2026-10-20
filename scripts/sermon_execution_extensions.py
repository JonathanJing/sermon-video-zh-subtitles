"""Transition facade: the implementation lives in tongxing_production.workflows.diagnostic.execution_extensions.

Both import paths name one module object, so attribute patches apply to both.
Diagnostic only, never release-eligible. Remove once nothing in scripts/ (the bounded diagnostic chain imports it) uses the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.diagnostic import execution_extensions as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
