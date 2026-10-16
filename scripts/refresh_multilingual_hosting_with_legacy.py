"""Transition facade: the implementation lives in tongxing_production.adapters.legacy.refresh_multilingual_hosting_with_legacy.

Both import paths name one module object, so attribute patches apply to both.
``python scripts/refresh_multilingual_hosting_with_legacy.py`` still runs the command. Remove once no caller
imports or runs the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.adapters.legacy import refresh_multilingual_hosting_with_legacy as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
