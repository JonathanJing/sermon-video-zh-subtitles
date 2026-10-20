"""Transition facade: the implementation lives in tongxing_production.workflows.diagnostic.openai_layer2_transport.

Both import paths name one module object, so attribute patches apply to both.
Diagnostic only, never release-eligible. Remove once nothing in scripts/ (scripts/run_codex_layer2_test.py imports it) uses the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import sermon_unified  # noqa: F401  binds the production package ports and the unified Backend
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import sermon_unified  # noqa: F401
from tongxing_production.workflows.diagnostic import openai_layer2_transport as _implementation  # noqa: E402

sys.modules[__name__] = _implementation
