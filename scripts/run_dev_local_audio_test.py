"""Compatibility entry point for the Dev local audio test driver."""
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.development import run_dev_local_audio_test as _implementation

if __name__ == "__main__":
    _implementation.main(sys.argv[1:])
else:
    sys.modules[__name__] = _implementation
