#!/usr/bin/env python3
"""Publish only the named files on a Firebase Hosting site, by cloning the live version.

Whole-site ``firebase deploy`` re-hashes and re-uploads every file (2.9 GB, 480 files on
2026-11-15) and a single-file correction does not need that. This tool clones the live
version, uploads only the files under ``--public`` whose gzip hash differs, finalizes and
releases, then verifies each published file over HTTPS.

It exists for presentation-only corrections that must leave the rest of the site intact: the
catalog's ``contentKind`` fix on 2026-11-16 is the first use. It never deletes files (the clone
carries every live file) and it refuses to run without ``--execute``; ``--no-release`` keeps the
current live release while finalizing the new version for inspection.

  PYTHONPATH=packages/production/src:. .venv/bin/python tools/ops/publish_hosting_files.py \\
      --site ai-for-god-sermon-audio --public <dir>/public --out <dir>/publish.json [--execute]

The receipt names the baseline version, the cloned version, the uploaded hashes, the released
version and the HTTPS readback of every uploaded file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

try:
    from tongxing_production.delivery import hosting_incremental
except ImportError:  # pragma: no cover - operator convenience
    raise SystemExit('run with PYTHONPATH=packages/production/src:.')
from tools.ops.hosting_incremental_publish import authenticated_request


def live_version(request, site: str, requested: str | None) -> str:
    if requested:
        return requested
    listing = request('GET', f'{hosting_incremental.API}/sites/{site}/releases?pageSize=10')
    releases = listing.get('releases') or []
    if not releases:
        raise SystemExit('site has no release to clone from; use firebase deploy')
    return max(releases, key=lambda row: row.get('name', '')).get('version', {}).get('name')


def build_plan(request, *, site: str, public: Path, baseline: str) -> dict:
    local = hosting_incremental.local_files(public)
    if not local:
        raise SystemExit('no files to publish under ' + str(public))
    remote = hosting_incremental.remote_files(request, site, baseline)
    if not remote:
        raise SystemExit('the live version lists no files to clone')
    digests = {path: hosting_incremental.digest(file) for path, file in local.items()}
    changed = sorted(path for path, value in digests.items() if remote.get(path) != value)
    return {'site': site, 'baselineVersion': baseline, 'localFiles': len(local),
            'remoteFiles': len(remote), 'changed': changed,
            'changedBytes': sum(local[path].stat().st_size for path in changed),
            'digests': digests, 'paths': local, 'startedAt': hosting_incremental.now()}


def verify(public_url: str, paths: dict[str, Path], cache_buster: str) -> list[dict]:
    """GET each published file and compare the served bytes with the local file."""
    checked = []
    for path, file in sorted(paths.items()):
        url = f'{public_url.rstrip("/")}{path}?v={cache_buster}'
        request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            status = response.status
        local = file.read_bytes()
        checked.append({'path': path, 'url': url, 'status': status, 'bytes': len(body),
                        'sha256': hashlib.sha256(body).hexdigest(),
                        'localSha256': hashlib.sha256(local).hexdigest(),
                        'matches': body == local})
    missing = [row['path'] for row in checked if not row['matches']]
    if missing:
        raise SystemExit('served bytes differ from the snapshot: ' + ', '.join(missing))
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--site', required=True, help='Firebase Hosting site id')
    parser.add_argument('--public', type=Path, required=True, help='directory whose files are the payload')
    parser.add_argument('--out', type=Path, required=True, help='receipt path')
    parser.add_argument('--public-url', help='HTTPS origin used for readback, e.g. https://<site>.web.app')
    parser.add_argument('--baseline-version', help='default: the version the live release points at')
    parser.add_argument('--execute', action='store_true', help='without it only a plan is written')
    parser.add_argument('--no-release', action='store_true', help='finalize but keep the live release')
    args = parser.parse_args()

    request = authenticated_request()
    baseline = live_version(request, args.site, args.baseline_version)
    plan = build_plan(request, site=args.site, public=args.public, baseline=baseline)
    summary = {key: plan[key] for key in ('site', 'baselineVersion', 'localFiles', 'remoteFiles',
                                          'changedBytes', 'changed')}
    print(json.dumps(summary, ensure_ascii=False)[:2000])
    if not plan['changed']:
        print('nothing to publish: the live version already serves these bytes')
        return 0
    if not args.execute:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({**summary, 'mode': 'dry-run'}, ensure_ascii=False, indent=1) + '\n',
                            encoding='utf-8')
        print(f'plan only; write the same command with --execute to publish ({args.out})')
        return 0

    receipt = hosting_incremental.deploy(request, plan=plan, out=args.out, release=not args.no_release)
    if args.public_url:
        receipt['readback'] = verify(args.public_url, {path: plan['paths'][path] for path in plan['changed']},
                                     receipt.get('clonedVersion', '').rsplit('/', 1)[-1] or 'readback')
        args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'baselineVersion': receipt['baselineVersion'], 'clonedVersion': receipt['clonedVersion'],
                      'uploaded': [row['path'] for row in receipt['uploaded']],
                      'release': receipt['release'],
                      'readback': [{'path': row['path'], 'matches': row['matches']}
                                   for row in receipt.get('readback', [])]}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
