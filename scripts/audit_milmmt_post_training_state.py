"""Compatibility entry for the MiLMMT post-training evidence audit."""

import importlib.util
from pathlib import Path
import sys

_IMPLEMENTATION_PATH = Path(__file__).resolve().parents[1] / "experiments/milmmt/audit_post_training_state.py"
_MODULE_NAME = "_tongxing_milmmt_post_training_state_audit"
_implementation = sys.modules.get(_MODULE_NAME)
if _implementation is None:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _IMPLEMENTATION_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"Cannot load MiLMMT audit at {_IMPLEMENTATION_PATH}")
    _implementation = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = _implementation
    _spec.loader.exec_module(_implementation)

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation


def __getattr__(name):
    # Also support callers that execute this file with spec_from_file_location.
    return getattr(_implementation, name)
