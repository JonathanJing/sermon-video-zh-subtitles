#!/usr/bin/env python3
"""Expose validated published alignment to clients consuming the v3 catalog.

Run against a new Hosting candidate. Only the catalog is changed; sidecars,
reviewed release packages, content, audio, and indexes remain byte-identical.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from build_published_english_reference import public_path, read_json, require


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bind_catalog(public, page_id):
    public = Path(public).resolve()
    catalog_path = public / 'multilingual-v3.json'
    catalog = read_json(catalog_path)
    require(catalog.get('schemaVersion') == 'sermon-multilingual-catalog-v3', 'Expected v3 catalog')
    pages = [p for p in catalog['pages'] if p['id'] == page_id]
    require(len(pages) == 1, 'Page must occur exactly once')
    page = pages[0]
    sidecar = read_json(public_path(public, f'/alignment/{page_id}.json'))
    require(sidecar.get('schemaVersion') == 'sermon-published-alignment-v1'
            and sidecar.get('pageId') == page_id
            and sidecar.get('sourceIdentitySha256') == page['sourceIdentitySha256'], 'Alignment source mismatch')
    require(set(sidecar['targets']) == set(page['targets']), 'Alignment locale mismatch')
    source_sha = None
    for locale, target in page['targets'].items():
        evidence = sidecar['targets'][locale]
        require(evidence['releasePackageJsonSha256'] == target['releasePackageJsonSha256'], 'Release binding mismatch')
        release = read_json(public_path(public, target['releasePackageUrl']), sha256=target['releasePackageJsonSha256'])
        require(release.get('status') == 'published_http_verified'
                and release.get('contentStatus') == target.get('contentStatus') == 'human_reviewed'
                and release.get('audioStatus') == target.get('audioStatus') == 'human_reviewed'
                and release.get('pageId') == page_id
                and release.get('targetLocale') == release.get('audioLocale') == release.get('contentLocale') == locale,
                'Unreviewed or mismatched release')
        assets = {}
        for role in ('audio', 'content'):
            matches = [a for a in release['assets'] if a['role'] == role]
            require(len(matches) == 1, f'Expected exactly one {role} asset')
            asset = matches[0]
            require(digest(public_path(public, asset['path'])) == asset['sha256'], f'{role} hash mismatch')
            assets[role] = asset
        content = read_json(public_path(public, assets['content']['path']))
        binding = evidence['audioFingerprint']
        require(binding.get('schemaVersion') == 'sermon-audio-fingerprint-binding-v1'
                and binding.get('algorithmVersion') == 'spectral-landmarks-v1'
                and binding.get('captureSeconds') == 10 and binding.get('pageId') == page_id
                and binding.get('trackSha256') == assets['audio']['sha256'], 'Invalid fingerprint binding')
        require(content.get('sourceMediaSha256') == binding['sourceSha256']
                and content.get('englishSourcePackageJsonSha256') == page['sourceIdentitySha256']
                and content.get('pageId') == page_id and content.get('targetLocale') == locale
                and binding.get('sourceStartSeconds') == 0
                and binding.get('sourceEndSeconds') == content.get('durationSeconds')
                and content['durationSeconds'] > 0, 'Fingerprint source/window mismatch')
        require(source_sha in (None, binding['sourceSha256']), 'Locales have different media')
        source_sha = binding['sourceSha256']
        index = read_json(public_path(public, binding['indexUrl']), sha256=binding['indexSha256'])
        require(binding['indexUrl'] == f"/fingerprints/{binding['indexSha256'][:16]}-landmarks.json", 'Index path mismatch')
        require(index.get('schemaVersion') == 'sermon-landmark-index-v1'
                and all(index.get(k) == binding[k] for k in ('algorithmVersion', 'pageId', 'sourceSha256', 'trackSha256',
                                                            'sourceStartSeconds', 'sourceEndSeconds'))
                and index.get('durationSeconds') == content['durationSeconds'], 'Index identity mismatch')
        require('audio' in target['capabilities'], 'Missing audio capability')
        require(target.get('audioFingerprint', binding) == binding, 'Existing binding conflicts')
        target['audioFingerprint'] = copy.deepcopy(binding)
        if 'alignment' not in target['capabilities']:
            target['capabilities'].append('alignment')
    require(page.get('sourceMediaSha256', source_sha) == source_sha, 'Existing media identity conflicts')
    page['sourceMediaSha256'] = source_sha
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', required=True, type=Path)
    parser.add_argument('--page-id', required=True)
    args = parser.parse_args()
    catalog = bind_catalog(args.public, args.page_id)
    output = args.public / 'multilingual-v3.json'
    before = digest(output)
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(catalogPath=str(output), beforeSha256=before, afterSha256=digest(output),
                          pageId=args.page_id, locales=list(next(p for p in catalog['pages'] if p['id'] == args.page_id)['targets']))))


if __name__ == '__main__':
    main()
