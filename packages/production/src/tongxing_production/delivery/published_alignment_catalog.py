#!/usr/bin/env python3
"""Expose validated published alignment to clients through the multilingual catalog.

Run against a new Hosting candidate. Only the catalogs are changed; sidecars,
published release packages, content, audio, and indexes remain byte-identical.

Without multilingual-v4.json only the v3 catalog is rewritten, as before. With it,
the binding is applied to v4 (machine-checked locales included) and v3 is rewritten
as exactly v4's human-only projection, so the two catalogs never diverge.

With multilingual-v5.json, --page-id names the source edition (the v4 page and
the alignment sidecar). The binding is validated on that v4 edition page exactly
as above, copied onto every v5 target of that edition, and v4 and v3 are then
required to be v5's projections, so all three catalogs change together.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path

from .published_english_reference import public_path, read_json, require
from . import contract as delivery_contract

V3, V4, V5 = 'multilingual-v3.json', 'multilingual-v4.json', 'multilingual-v5.json'
PUBLISHED = {'human_reviewed', 'machine_checked'}


# Seconds a dubbed track may end after the approved clip and still count as source-clocked.
TAIL_OVERRUN_ALLOWANCE = 1.0
# Content `sourceWindow` block; its length may differ from durationSeconds by the
# listening-web reader's tolerance (apps/listening-web/published-weeks.mjs).
SOURCE_WINDOW = 'sermon-original-recording-window-v1'
WINDOW_DURATION_TOLERANCE = .001

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bind_catalog(public, page_id):
    """The rebound v3 catalog (v4's human-only projection when v4 is present)."""
    return bind_catalogs(public, page_id)[V3]


def bind_catalogs(public, page_id):
    """Return {catalog file name: rebound catalog}; v4 and v5 are included only when published."""
    public = Path(public).resolve()
    v3 = read_json(public / V3)
    require(v3.get('schemaVersion') == 'sermon-multilingual-catalog-v3', 'Expected v3 catalog')
    if not (public / V4).exists():
        require(not (public / V5).exists(), 'multilingual-v5.json requires multilingual-v4.json')
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
    if not (public / V5).exists():
        return {V4: bound, V3: projection}
    v5 = delivery_contract.validate_catalog_schema(read_json(public / V5))
    require(v5.get('schemaVersion') == delivery_contract.CATALOG_V5, 'Expected v5 catalog')
    # v3, v4, v5 are written in that order, so an interrupted run may leave v4 already bound.
    require(v4 in (delivery_contract.project_legacy_catalog_v4(v5), bound),
            'multilingual-v4.json is not the edition projection of multilingual-v5.json')
    bound_v5 = delivery_contract.validate_catalog_schema(_bind_v5(v5, bound, page_id))
    require(delivery_contract.project_legacy_catalog_v4(bound_v5) == bound,
            'Alignment binding differs between v5 and its v4 projection')
    return {V5: bound_v5, V4: bound, V3: projection}


def _bind_v5(v5, bound_v4, page_id):
    """Copy the binding validated on the v4 edition page onto each v5 target of that edition."""
    v5 = copy.deepcopy(v5)
    edition = next(p for p in bound_v4['pages'] if p['id'] == page_id)
    found = set()
    for page in v5['pages']:
        for locale, target in page['targets'].items():
            if delivery_contract.target_source_identity(page, target)[0] != page_id:
                continue
            require(locale not in found, 'Edition locale occurs twice in v5')
            found.add(locale)
            bound_target = edition['targets'][locale]
            target['audioFingerprint'] = copy.deepcopy(bound_target['audioFingerprint'])
            target['capabilities'] = list(bound_target['capabilities'])
            if page.get('sourceMode') != 'per_target':
                page['sourceMediaSha256'] = edition['sourceMediaSha256']
    require(found == set(edition['targets']), 'v5 edition locales differ from the v4 edition page')
    return v5


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
    source_sha = source_window = None
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
        start, end = binding.get('sourceStartSeconds'), binding.get('sourceEndSeconds')
        duration = content.get('durationSeconds')
        require(_seconds(start) and _seconds(end) and _seconds(duration) and 0 <= start < end and duration > 0
                and content.get('sourceMediaSha256') == binding['sourceSha256']
                and _window_matches(content.get('sourceWindow'), binding['sourceSha256'], start, end, duration)
                and content.get('englishSourcePackageJsonSha256') == page['sourceIdentitySha256']
                and content.get('pageId') == page_id and content.get('targetLocale') == locale,
                'Fingerprint source/window mismatch')
        # Every locale shares the page's source identity, so one approved window.
        require(source_window in (None, (start, end)), 'Locales have different source windows')
        source_window = (start, end)
        if machine:
            # Landmark alignment maps the dub 1:1 onto source time; a dub on its own
            # clock (e.g. a condensed spoken script) cannot be located that way.
            require(content.get('status') == release['contentStatus'], 'Content status differs from its release')
            # A natural dub may end up to TAIL_OVERRUN_ALLOWANCE after the source (its final
            # sentence outlasting the English, recorded in the Layer 3 trim evidence); it still
            # runs on source time. A shorter or longer track is on its own clock.
            drift = content.get('audioDurationSeconds', content['durationSeconds']) - content['durationSeconds']
            require(-.1 < drift < TAIL_OVERRUN_ALLOWANCE + .1, 'Dub is not on the source clock')
        require(source_sha in (None, binding['sourceSha256']), 'Locales have different media')
        source_sha = binding['sourceSha256']
        index = read_json(public_path(public, binding['indexUrl']), sha256=binding['indexSha256'])
        require(binding['indexUrl'] == f"/fingerprints/{binding['indexSha256'][:16]}-landmarks.json", 'Index path mismatch')
        require(index.get('schemaVersion') == 'sermon-landmark-index-v1'
                and all(index.get(k) == binding[k] for k in ('algorithmVersion', 'pageId', 'sourceSha256', 'trackSha256',
                                                            'sourceStartSeconds', 'sourceEndSeconds'))
                and index.get('durationSeconds') == end - start, 'Index identity mismatch')
        require('audio' in target['capabilities'], 'Missing audio capability')
        require(target.get('audioFingerprint', binding) == binding, 'Existing binding conflicts')
        target['audioFingerprint'] = copy.deepcopy(binding)
        if 'alignment' not in target['capabilities']:
            target['capabilities'].append('alignment')
    require(page.get('sourceMediaSha256', source_sha) == source_sha, 'Existing media identity conflicts')
    page['sourceMediaSha256'] = source_sha
    return catalog


def _seconds(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _window_matches(window, media_sha256, start, end, duration):
    """The fingerprint window is the content's approved source window.

    Content with a ``sourceWindow`` block must name the same master media and
    endpoints, and its duration may differ from the window length by the
    published reader's 1 ms tolerance. Historical content without the block keeps
    the zero-origin rule: the window starts at 0 and ends at the content duration.
    """
    if window is None:
        return start == 0 and end == duration
    return (isinstance(window, dict) and window.get('schemaVersion') == SOURCE_WINDOW
            and window.get('mediaSha256') == media_sha256
            and window.get('startSeconds') == start and window.get('endSeconds') == end
            and abs(end - start - duration) < WINDOW_DURATION_TOLERANCE)


def write_catalogs(public, catalogs, page_id):
    """Replace each catalog atomically, v3 before v4 before v5 (see bind_catalogs)."""
    rows = []
    for name in (V3, V4, V5):
        if name not in catalogs:
            continue
        output = Path(public) / name
        before = digest(output)
        staged = output.with_name(f'.{name}.binding')
        staged.write_text(json.dumps(catalogs[name], ensure_ascii=False, indent=2) + '\n')
        os.replace(staged, output)
        # A page with only machine-checked locales is absent from the v3 projection;
        # in v5 the edition's locales sit on per_target family pages.
        edition = lambda page, target: target['editionId'] if page.get('sourceMode') == 'per_target' else page['id']
        rows.append(dict(catalogPath=str(output), beforeSha256=before, afterSha256=digest(output), pageId=page_id,
                         locales=[locale for page in catalogs[name]['pages']
                                  for locale, target in page.get('targets', {}).items() if edition(page, target) == page_id]))
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
