"""Transition facade for tools.development.docs_change_gate.

Keep CI's direct command, module command, imports, and file-spec loading.
"""
from pathlib import Path
import sys

if __package__ in {None, ""}:  # python3 scripts/docs_change_gate.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.development import docs_change_gate as _implementation
from tools.development.docs_change_gate import *  # noqa: F403,F401 - file-spec compatibility

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
if __name__ == "scripts.docs_change_gate":
    sys.modules[__name__] = _implementation
