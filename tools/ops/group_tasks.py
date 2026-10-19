"""Operator entry for per-group tasks (DEV-GRP). ``plan`` is read only.

    .venv/bin/python tools/ops/group_tasks.py plan --manifest <inputs.json> [--locale ko --group-id <id> ...]

Binds the production host (repository root, plugin root, waiver closure) before the
package reads current stage implementation identities. Dispatches nothing.
"""
from __future__ import annotations

from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import tongxing_host  # noqa: F401  (configures the package host)
from tongxing_production.orchestration import group_plan

if __name__ == "__main__":
    raise SystemExit(group_plan.main())
