"""Transition facade: the implementation lives in tongxing_production.source.youtube_data_api.

Both import paths name one module object, so attribute patches apply to both.
scripts/tongxing_host.py binds ``scripts.youtube_data_api`` for the dual_pdf
workflows, and its bytes are in the G1 closures; remove in the next closure window.
``python scripts/youtube_data_api.py`` still runs the metadata command.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.source import youtube_data_api as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
