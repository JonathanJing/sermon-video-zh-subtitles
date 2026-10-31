#!/usr/bin/env python3
"""Prepare a sealed single-source sermon import on a Dev Hosting baseline; never deploy."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import tongxing_host  # noqa: E402,F401
from tongxing_production.delivery import single_source_dev_overlay  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--asset-source', type=Path, required=True)
    parser.add_argument('--page-id', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(single_source_dev_overlay.prepare(args.baseline, args.asset_source,
                                                      args.page_id, args.out), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
