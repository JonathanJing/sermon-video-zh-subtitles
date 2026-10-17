#!/usr/bin/env python3
"""Compatibility entry point for tools/ops/prepare_cloud_run_realtime_update_plan.py.

Keep the old CLI and module path for deployment prep and preflight callers.
"""

from pathlib import Path
import sys

try:
    from tools.ops import prepare_cloud_run_realtime_update_plan as _implementation
except ModuleNotFoundError:  # direct invocation from scripts/ outside the repo root
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.ops import prepare_cloud_run_realtime_update_plan as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
