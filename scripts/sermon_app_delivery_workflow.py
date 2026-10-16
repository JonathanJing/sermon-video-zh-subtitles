"""Transition facade: the implementation lives in tongxing_production.delivery.app_workflow.

Both import paths name one module object, so attribute patches apply to both.
``python scripts/sermon_app_delivery_workflow.py`` still runs the command, and durable
App delivery job requests record this path as the worker entry point, so keep it while
any such request can be recovered.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.delivery import app_workflow as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
