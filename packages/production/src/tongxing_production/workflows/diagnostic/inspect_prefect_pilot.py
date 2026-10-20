"""Print a private, read-only report of a frozen local MOCK pilot. No dispatch.

Run it as ``tools/ops/run.py workflows.diagnostic.inspect_prefect_pilot``."""
import argparse
import json
from pathlib import Path
from tongxing_production.workflows.diagnostic.pilot_evidence import inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--offline-diagnosis', action='store_true', help='Run in-memory lifecycle fixture, no model')
    args = parser.parse_args()
    print(json.dumps(inspect(args.root, diagnose_offline=args.offline_diagnosis), sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
