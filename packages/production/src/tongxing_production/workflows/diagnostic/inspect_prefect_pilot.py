#!/usr/bin/env python3
"""Print a private, read-only report of a frozen local MOCK pilot. No dispatch."""
import argparse
import json
from pathlib import Path
import sys
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from scripts.sermon_pilot_evidence import inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--offline-diagnosis', action='store_true', help='Run in-memory lifecycle fixture, no model')
    args = parser.parse_args()
    print(json.dumps(inspect(args.root, diagnose_offline=args.offline_diagnosis), sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
