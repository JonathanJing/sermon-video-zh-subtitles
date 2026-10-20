"""Operator entry for per-group tasks (DEV-GRP). ``plan`` and ``status`` are read only.

    .venv/bin/python tools/ops/group_tasks.py plan   --manifest <inputs.json> [--locale ko --group-id <id> ...]
    .venv/bin/python tools/ops/group_tasks.py status --config <run-config.json>
    .venv/bin/python tools/ops/group_tasks.py run    --config <run-config.json> [--group-id <id> ...]
    .venv/bin/python tools/ops/group_tasks.py merge  --config <run-config.json>

Binds the production host (repository root, plugin root, waiver closure) before the
package reads current stage implementation identities. ``plan``/``status`` dispatch
nothing; ``run`` needs a budget document or ``--confirm-unbudgeted``.
"""
from __future__ import annotations

from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import tongxing_host  # noqa: F401  (configures the package host)
from tongxing_production.orchestration import group_pipeline

if __name__ == "__main__":
    raise SystemExit(group_pipeline.main())
