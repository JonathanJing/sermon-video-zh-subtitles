"""Transition facade: the implementation lives in tongxing_production.workflows.prepared.capabilities.

Both import paths name one module object, so attribute patches apply to both.
``python scripts/sermon_unified_capabilities.py`` still runs the command.
Remove once no caller imports or runs the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from scripts import sermon_unified  # noqa: F401,E402  binds the orchestration this stage composes
from tongxing_production.workflows.prepared import capabilities as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
