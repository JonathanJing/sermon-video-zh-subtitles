"""Compatibility entry point for tools.ops.project_codex_credit_usage."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import project_codex_credit_usage as _implementation

if __name__ == '__main__':
    _implementation.main()
sys.modules[__name__] = _implementation
