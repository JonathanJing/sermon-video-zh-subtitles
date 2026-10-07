#!/usr/bin/env python3
"""Expose validated published alignment to clients through the multilingual catalog.

Run against a new Hosting candidate. Only the catalogs are changed; sidecars,
published release packages, content, audio, and indexes remain byte-identical.

Without multilingual-v4.json only the v3 catalog is rewritten, as before. With it,
the binding is applied to v4 (machine-checked locales included) and v3 is rewritten
as exactly v4's human-only projection, so the two catalogs never diverge.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from build_published_english_reference import public_path, read_json, require
import delivery_contract

V3, V4 = 'multilingual-v3.json', 'multilingual-v4.json'
PUBLISHED = {'human_reviewed', 'machine_checked'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bind_catalog(public, page_id):
    """The rebound v3 catalog (v4's human-only projection when v4 is present)."""
    return bind_catalogs(public, page_id)[V3]


def bind_catalogs(public, page_id):
    """Return {catalog file name: rebound catalog}; v4 is included only when published."""
    public = Path(public).resolve()
    v3 = read_json(public / V3)
    require(v3.get('schemaVersion') == 'sermon-multilingual-catalog-v3', 'Expected v3 catalog')
    if not (public / V4).exists():
        return {V3: _bind(public, v3, page_id, machine=False)}
    v4 = read_json(public / V4)
    require(v4.get('schemaVersion') == delivery_contract.CATALOG_V4, 'Expected v4 catalog')
    delivery_contract.validate_catalog_schema(v4)
    bound = delivery_contract.validate_catalog_schema(_bind(public, v4, page_id, machine=True))
    projection = delivery_contract.project_human_catalog(bound)
    # main() writes v3 before v4, so an interrupted run leaves v3 already equal to the
    # new projection; any other v3 was changed outside the seal and is refused.
    require(v3 in (delivery_contract.project_human_catalog(v4), projection),
            'multilingual-v3.json is not the human-only projection of multilingual-v4.json')
    return {V4: bound, V3: projection}


def _bind(public, catalog, page_id, *, machine):
    catalog = copy.deepcopy(catalog)
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
        if machine:
            # Statuses must already agree between release and catalog; nothing is
            # promoted, so a machine-checked target stays machine_checked under /releases-v4/.
            reviewed = (release.get('contentStatus') == target.get('contentStatus') in PUBLISHED
                        and release.get('audioStatus') == target.get('audioStatus') in PUBLISHED
                        and (release.get('schemaVersion') == delivery_contract.RELEASE_V4)
                        == delivery_contract.machine_checked(target)
                        and target['releasePackageUrl'] == delivery_contract.release_path(
                            {**release, 'schemaVersion': release.get('schemaVersion')})
                        and (release.get('schemaVersion') not in delivery_contract.FOUR_PRODUCT_RELEASES
                             or release.get('englishSourcePackageJsonSha256') == page['sourceIdentitySha256']))
        else:
            reviewed = (release.get('contentStatus') == target.get('contentStatus') == 'human_reviewed'
                        and release.get('audioStatus') == target.get('audioStatus') == 'human_reviewed')
        require(release.get('status') == 'published_http_verified' and reviewed
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
        if machine:
            # Landmark alignment maps the dub 1:1 onto source time; a dub on its own
            # clock (e.g. a condensed spoken script) cannot be located that way.
            require(content.get('status') == release['contentStatus'], 'Content status differs from its release')
            require(abs(content.get('audioDurationSeconds', content['durationSeconds'])
                        - content['durationSeconds']) < .1, 'Dub is not on the source clock')
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


def write_catalogs(public, catalogs, page_id):
    """Replace each catalog atomically, v3 before v4 (see bind_catalogs)."""
    rows = []
    for name in (V3, V4):
        if name not in catalogs:
            continue
        output = Path(public) / name
        before = digest(output)
        staged = output.with_name(f'.{name}.binding')
        staged.write_text(json.dumps(catalogs[name], ensure_ascii=False, indent=2) + '\n')
        os.replace(staged, output)
        rows.append(dict(catalogPath=str(output), beforeSha256=before, afterSha256=digest(output), pageId=page_id,
                         locales=list(next(p for p in catalogs[name]['pages'] if p['id'] == page_id)['targets'])))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', required=True, type=Path)
    parser.add_argument('--page-id', required=True)
    args = parser.parse_args()
    rows = write_catalogs(args.public, bind_catalogs(args.public, args.page_id), args.page_id)
    # A v3-only snapshot keeps its single-catalog report shape.
    print(json.dumps(rows[0] if len(rows) == 1 else dict(pageId=args.page_id, catalogs=rows)))


if __name__ == '__main__':
    main()
