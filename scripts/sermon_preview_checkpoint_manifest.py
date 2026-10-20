"""Transition facade: the implementation lives in tongxing_production.workflows.diagnostic.preview_checkpoint_manifest.

Both import paths name one module object, so attribute patches apply to both.
Diagnostic only, never release-eligible. Remove once nothing in scripts/ (the diagnostic preview worker and the fresh diagnostic import it) uses the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.diagnostic import preview_checkpoint_manifest as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
