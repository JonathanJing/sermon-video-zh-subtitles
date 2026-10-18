"""Compatibility entry for the MiLMMT post-training evidence audit."""

from pathlib import Path
import sys

try:
    from experiments.milmmt import audit_post_training_state as _implementation
except ModuleNotFoundError:
    # Direct execution from outside the repository must still find the implementation.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from experiments.milmmt import audit_post_training_state as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation


def __getattr__(name):
    # Also support callers that execute this file with spec_from_file_location.
    return getattr(_implementation, name)
