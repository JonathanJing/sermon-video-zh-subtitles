#!/usr/bin/env python3
"""Prepare one production-safe mixed-source Hosting snapshot without deploying it.

The command-line entry; the implementation is
tongxing_production.delivery.baseline.mixed_source_catalog_overlay.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Run by path from tools/ops: bind the production package to this checkout first.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.delivery import baseline  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path,
                        help='Complete production live baseline snapshot')
    parser.add_argument('--catalog', required=True, type=Path,
                        help='One-page sermon-multilingual-catalog-v5 candidate')
    parser.add_argument('--release-plan', required=True, type=Path,
                        help='CAS-bound sermon-locale-release-plan-v1')
    parser.add_argument('--out', required=True, type=Path,
                        help='New immutable Hosting candidate directory')
    parser.add_argument('--environment', choices=('production', 'dev'), default='production')
    args = parser.parse_args(argv)
    result = baseline.mixed_source_catalog_overlay(
        args.baseline, args.catalog, args.release_plan, args.out, environment=args.environment)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
