"""Transition facade: the implementation lives in tongxing_production.workflows.supervisor.agent.

Both import paths name one module object, so attribute patches apply to both.
backend/app.py and the Cloud Run job run ``scripts/run_sermon_production_supervisor_agent.py``
by path in the deployed image, so remove it together with the next Cloud Run deploy
(decision D-2). Prefer ``tools/ops/run.py workflows.supervisor.agent``.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.workflows.supervisor import agent as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
