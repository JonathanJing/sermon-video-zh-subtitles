"""Legacy CLI and import surface for the read-only weekly DAG projection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  configures observability readers
except ModuleNotFoundError:  # direct script execution outside the checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401

from tongxing_production.observability import weekly_projection as _projection
from tongxing_production.observability.weekly_projection import *  # noqa: F401,F403


def __getattr__(name):
    return getattr(_projection, name)


def main():
    parser = argparse.ArgumentParser(description=_projection.__doc__)
    parser.add_argument('--accounting-dir', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    # Keep projections away from the append-only source and existing outputs.
    from scripts import sermon_trace_artifacts as artifacts
    artifacts.new_directory(args.out_dir)
    report = project(args.accounting_dir)
    for name, content in [('report.json', json.dumps(report, indent=2, allow_nan=False) + '\n'),
                          ('report.md', markdown(report))]:
        artifacts.write(args.out_dir / name, content)
    return 0 if report['status'] == 'projected' else 1


if __name__ == '__main__':
    sys.exit(main())
