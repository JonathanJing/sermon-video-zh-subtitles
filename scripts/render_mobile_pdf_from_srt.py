"""Compatibility entry for the mobile PDF renderer in the dual-PDF package."""

from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  makes the package importable from this checkout
except ModuleNotFoundError:  # executed by path from outside the checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.dual_pdf import mobile_pdf as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
