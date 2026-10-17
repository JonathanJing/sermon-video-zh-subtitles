"""Compatibility entry for the dual-PDF post-live timeline job.

The implementation and the legacy import path share one module object, so
callers that patch this module still intercept the job's collaborators.
"""

from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly from scripts/ or a non-repository CWD
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.dual_pdf import timeline as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
