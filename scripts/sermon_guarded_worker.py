"""Transition facade: the implementation lives in tongxing_production.orchestration.guarded_worker.

Both import paths name one module object, so attribute patches apply to both.
``python scripts/sermon_guarded_worker.py`` still runs the command; prefer ``tools/ops/run.py orchestration.guarded_worker``.
Remove once nothing in scripts/ (the production supervisor runs it) uses the old path.
"""
import sys

from tongxing_production.orchestration import guarded_worker as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
