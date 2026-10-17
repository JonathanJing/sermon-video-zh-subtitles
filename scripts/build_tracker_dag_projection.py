"""Transition facade for the read-only Tracker DAG projection builder.

The old import and CLI path share one module object with the package implementation.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds production package ports
except ModuleNotFoundError:  # direct execution from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.observability.projections import tracker_dag_projection as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
