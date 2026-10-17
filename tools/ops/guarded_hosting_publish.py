#!/usr/bin/env python3
"""Hosting publisher with remote generation-fenced lease and immutable live baseline.

The command-line entry (L4 D8); the implementation lives in
tongxing_production.delivery.publication. ``scripts/guarded_hosting_publish.py`` and
``python -m scripts.guarded_hosting_publish`` still run this command.
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
from tongxing_production.delivery import publication as _implementation  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=_implementation.__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    _implementation.contract.validate_intent(config['intent'], config['routes'])
    _implementation.contract.validate_catalog_snapshot(config['snapshot'])
    if not args.execute:
        print(json.dumps({'status': 'validated_not_deployed'}))
        return
    import urllib.request
    def reader(url, *, timeout=60):
        with urllib.request.urlopen(urllib.request.Request(url, headers={'Cache-Control': 'no-cache'}), timeout=timeout) as response:
            return response.status, response.read()
    result = _implementation.publish(**config, request=_implementation.authenticated_transport(), reader=reader)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
