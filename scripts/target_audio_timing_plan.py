"""Transition facade: the implementation lives in tongxing_production.audio.timing_plan.

Both import paths name one module object, so attribute patches apply to both.
``python scripts/target_audio_timing_plan.py`` still runs the command (runbooks and the Spark launchers run
this path). Remove once no caller imports or runs the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.audio import timing_plan as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
