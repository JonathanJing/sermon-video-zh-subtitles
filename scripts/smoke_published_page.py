"""Transition facade: the tool lives in tools/ops/smoke_published_page.py.

Both import paths name one module object, so attribute patches apply to both.
``python scripts/smoke_published_page.py`` and ``python -m scripts.smoke_published_page`` still run the command.
Remove once no caller imports or runs the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tools.ops import smoke_published_page as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
