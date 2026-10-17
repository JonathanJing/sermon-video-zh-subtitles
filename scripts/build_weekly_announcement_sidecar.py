"""Compatibility entry for the weekly announcement sidecar binder."""
from pathlib import Path
import sys

_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_root / "packages/production/src"))

from tongxing_production.delivery.posters import announcement_sidecar as _implementation


def __getattr__(name):
    # Dynamic file loaders keep the module object they created, even after
    # sys.modules receives the alias below.
    return getattr(_implementation, name)


if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
