"""Legacy CLI and import facade for the CUV translation producer."""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.text import cuv_translation as _implementation  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
