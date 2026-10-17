#!/usr/bin/env python3
"""Acquire a complete live-bound Hosting snapshot or isolated Dev overlay.

The command-line entry (L4 D8); the implementation lives in
tongxing_production.delivery.baseline. ``scripts/prepare_dev_simulated_publication.py`` and
``python -m scripts.prepare_dev_simulated_publication`` still run this command.
"""
import argparse
import json
from pathlib import Path
import sys

# Run by path from tools/ops: bind the production package to this checkout first.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.delivery import baseline as _implementation  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=_implementation.__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    b = commands.add_parser('baseline')
    b.add_argument('--out', required=True, type=Path)
    b.add_argument('--cache-public', type=Path)
    b.add_argument('--cache-receipt', type=Path)
    b.add_argument('--environment', choices=('dev', 'production'), default='dev')
    a = commands.add_parser('asset-first')
    a.add_argument('--baseline', required=True, type=Path)
    a.add_argument('--prepared', required=True, type=Path)
    a.add_argument('--out', required=True, type=Path)
    a.add_argument('--source-video', type=Path)
    o = commands.add_parser('overlay')
    o.add_argument('--baseline', required=True, type=Path)
    o.add_argument('--overlay-public', required=True, type=Path)
    o.add_argument('--catalog', required=True, type=Path)
    o.add_argument('--out', required=True, type=Path)
    plan = commands.add_parser('release-plan')
    plan.add_argument('--baseline', required=True, type=Path)
    plan.add_argument('--prepared', required=True, type=Path)
    plan.add_argument('--out', required=True, type=Path)
    repair = commands.add_parser('runtime-repair')
    repair.add_argument('--baseline', required=True, type=Path)
    repair.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.action == 'baseline':
        result = _implementation.baseline(args.out, cache_public=args.cache_public, cache_receipt=args.cache_receipt,
                          environment=args.environment)
    elif args.action == 'asset-first':
        result = _implementation.asset_first(args.baseline, args.prepared, args.out, args.source_video)
    elif args.action == 'release-plan':
        result = _implementation.release_plan(args.baseline, args.prepared, args.out)
    elif args.action == 'runtime-repair':
        result = _implementation.runtime_repair(args.baseline, args.out)
    else:
        result = _implementation.overlay(args.baseline, args.overlay_public, args.catalog, args.out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
