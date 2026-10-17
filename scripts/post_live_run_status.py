"""Compatibility alias for the dual-PDF status ledger."""

from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.dual_pdf import run_status as _implementation

sys.modules[__name__] = _implementation
