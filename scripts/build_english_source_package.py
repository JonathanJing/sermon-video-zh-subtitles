"""Transition facade: the implementation lives in tongxing_production.source.english_source_package.

Both import paths name one module object, so attribute patches apply to both.
``python scripts/build_english_source_package.py`` still runs the command. Remove once no caller
imports or runs the old path.
"""
from pathlib import Path
import sys

if __name__ == "__main__":  # direct execution: the checkout root is not on sys.path yet
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.source import english_source_package as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
