"""Transition facade: the implementation lives in tongxing_production.observability.cost_isolation.

Both import paths name one module object, so attribute patches apply to both.
``python -m scripts.sermon_cost_isolation`` still runs the command; prefer
``tools/ops/run.py observability.cost_isolation``. Remove once no caller imports or runs the old path.
"""
import sys

from tongxing_production.observability import cost_isolation as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
