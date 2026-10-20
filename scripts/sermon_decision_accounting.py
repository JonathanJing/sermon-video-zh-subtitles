"""Transition facade: the implementation lives in tongxing_production.orchestration.supervisor.decision_accounting.

Both import paths name one module object, so attribute patches apply to both.
scripts/tongxing_host.py names ``scripts.sermon_decision_accounting`` as a load-time
import of the weekly projection; remove it in the next closure window.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.orchestration.supervisor import decision_accounting as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
