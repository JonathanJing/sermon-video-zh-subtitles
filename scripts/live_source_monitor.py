"""Transition facade: the implementation lives in tongxing_production.workflows.dual_pdf.live_source_monitor.

Both import paths name one module object, so attribute patches apply to both.
scripts/tongxing_host.py binds ``scripts.live_source_monitor`` for the dual_pdf
workflows and backend/app.py imports it in the Cloud Run image, so remove it in the
next closure window together with the next Cloud Run deploy.
``python scripts/live_source_monitor.py`` still runs the monitor; prefer
``tools/ops/run.py workflows.dual_pdf.live_source_monitor``.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.dual_pdf import live_source_monitor as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
