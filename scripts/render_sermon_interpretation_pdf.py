"""Compatibility entry for the dual-PDF interpretation renderer."""

from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the package from this checkout
except ModuleNotFoundError:  # executed by path from outside the checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.dual_pdf import interpretation_pdf as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
