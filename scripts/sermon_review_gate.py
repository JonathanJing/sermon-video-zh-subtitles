"""Legacy import facade for strict Layer 2 review admission."""

from pathlib import Path
import sys

try:
    from scripts import sermon_review_contracts as _contracts  # noqa: F401  binds checkout schemas
except ModuleNotFoundError:  # bare import from a script run inside scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import sermon_review_contracts as _contracts  # noqa: F401

from tongxing_production.text import strict_review_gate as _implementation

sys.modules[__name__] = _implementation
