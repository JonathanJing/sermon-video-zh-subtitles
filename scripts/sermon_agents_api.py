"""Transition facade: the implementation lives in tongxing_production.orchestration.supervisor.agents_api.

Both import paths name one module object, so attribute patches apply to both.
Remove once no caller imports the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.orchestration.supervisor import agents_api as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
