"""Transition import facade for tools.ops.patch_firebase_dev_app_banner."""
from pathlib import Path
import sys

if __package__ in {None, ""}:  # imported by a directly run scripts/ installer
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import patch_firebase_dev_app_banner as _implementation

sys.modules[__name__] = _implementation
