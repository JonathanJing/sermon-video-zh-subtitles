"""Transition facade: the implementation lives in tongxing_production.workflows.supervisor.production.

Both import paths name one module object, so attribute patches apply to both.
backend/app.py imports it in the Cloud Run image, so remove it together with the
next Cloud Run deploy (decision D-2). Prefer
``tools/ops/run.py workflows.supervisor.production``-style package imports.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.supervisor import production as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
