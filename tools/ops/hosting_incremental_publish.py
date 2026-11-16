#!/usr/bin/env python3
"""Publish a hosting snapshot incrementally through the Hosting REST API (manual entry).

The publication path uses the same code (``tongxing_production.delivery.hosting_incremental``)
as its default route; this tool stays for an operator who needs to plan or run one publish by
hand against a snapshot directory. It clones the live version, uploads only the files whose
gzip hash changed, finalizes and releases, and writes a receipt naming exactly what it did.

``firebase deploy`` re-hashes and re-uploads the whole site snapshot in one node process with
200 concurrent uploads; on a 2.9 GB site on a 36 GiB Mac that process was killed by macOS
jetsam (low swap) on 2026-11-14 and again on 2026-11-15.

  PYTHONPATH=packages/production/src:. .venv/bin/python tools/ops/hosting_incremental_publish.py \
      --site ai-for-god-sermon-audio --public <snapshot>/public \
      --out <snapshot>/incremental-publish.json [--execute] [--no-release]

Without ``--execute`` it only plans: it lists the baseline version, hashes the snapshot and
writes the plan, changing nothing remotely.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from tongxing_production.delivery import hosting_incremental
except ImportError:  # pragma: no cover - operator convenience
    raise SystemExit('run with PYTHONPATH=packages/production/src:.')


def authenticated_request():
    """An ADC-authorised request(method, url, data=, headers=, timeout=) for the publisher."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    session = AuthorizedSession(credentials)

    def request(method, url, *, data=None, headers=None, timeout=60):
        response = session.request(method, url, data=data, headers=headers, timeout=timeout)
        if response.status_code not in (200, 201, 204):
            raise ValueError(f'{method} {url.split("?")[0]} rejected: HTTP {response.status_code}')
        return response.json() if response.content else {}
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--site', required=True)
    parser.add_argument('--public', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline-version', help='default: the version the live release points at')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--no-release', action='store_true', help='finalize the version but keep the live release')
    args = parser.parse_args()

    request = authenticated_request()
    baseline = args.baseline_version
    if not baseline:
        listing = request('GET', f'{hosting_incremental.API}/sites/{args.site}/releases?pageSize=10')
        releases = listing.get('releases') or []
        if not releases:
            raise SystemExit('site has no release to clone from; use firebase deploy')
        baseline = max(releases, key=lambda row: row.get('name', '')).get('version', {}).get('name')
    config_path = args.public.parent / 'firebase.json'
    ignore = json.loads(config_path.read_text())['hosting'].get('ignore') if config_path.exists() else None
    try:
        plan = hosting_incremental.plan(request, site=args.site, public=args.public,
                                        baseline_version=baseline, ignore=ignore)
    except hosting_incremental.NotIncremental as reason:
        raise SystemExit('this snapshot needs a whole-site deploy: ' + str(reason))

    print(json.dumps({key: plan[key] for key in ('site', 'baselineVersion', 'localFiles',
                                                 'remoteFiles', 'changedBytes', 'changed')},
                     ensure_ascii=False)[:2000])
    if not args.execute:
        args.out.write_text(json.dumps({**{key: plan[key] for key in plan if key != 'digests'},
                                        'mode': 'dry-run'}, ensure_ascii=False, indent=1) + '\n',
                            encoding='utf-8')
        return 0
    receipt = hosting_incremental.deploy(request, plan=plan, out=args.out,
                                         release=not args.no_release)
    print(json.dumps({'clonedVersion': receipt['clonedVersion'],
                      'uploaded': len(receipt['uploaded']),
                      'encodedBytes': sum(row['encodedBytes'] for row in receipt['uploaded']),
                      'release': receipt['release']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
