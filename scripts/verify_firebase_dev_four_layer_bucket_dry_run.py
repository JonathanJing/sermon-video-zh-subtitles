"""Compatibility entry point for the Firebase Dev bucket readback."""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import verify_firebase_dev_four_layer_bucket_dry_run as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
