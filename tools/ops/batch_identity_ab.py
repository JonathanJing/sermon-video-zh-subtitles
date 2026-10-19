"""Operator entry for the DEV-GRP-005 batch-identity A/B (select, pack, record). Renders nothing.

    .venv/bin/python tools/ops/batch_identity_ab.py select --speech-job <formal speech job> --out selection.json
    .venv/bin/python tools/ops/batch_identity_ab.py pack --selection selection.json --preview <preview out> --out packet/
    .venv/bin/python tools/ops/batch_identity_ab.py record --packet packet/ --verdicts verdicts.json \\
        --listener "<name>" --listened-at <ISO time> --out result.json
"""
from __future__ import annotations

from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import tongxing_host  # noqa: F401  (configures the package host the renderer reads)
from tongxing_production.audio import batch_identity_ab

if __name__ == "__main__":
    raise SystemExit(batch_identity_ab.main())
