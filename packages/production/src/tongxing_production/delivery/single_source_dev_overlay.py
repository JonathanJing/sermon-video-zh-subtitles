"""Prepare a single-source published sermon on an independently sealed Dev baseline.

This module does not contact Hosting or deploy. It imports only assets named by a
sealed source catalog/release, retains their immutable bytes and source identity,
keeps all Dev catalog entries and defaults, and produces a guarded publish config.
The source's HTTP verification is not evidence of a successful Dev readback.
"""
from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from html.parser import HTMLParser
import shutil
from urllib.parse import urljoin, urlsplit
from pathlib import Path

from . import baseline, contract
from . import published_alignment_catalog


def verify_live_baseline(base, receipt):
    """Bind every public byte to the acquired version, excluding Firebase-managed paths."""
    rows = receipt.get('rows')
    contract.require(isinstance(rows, list) and rows, 'Baseline live inventory is missing')
    all_names, live_public = set(), {}
    for row in rows:
        value = row.get('path')
        contract.require(isinstance(value, str) and value.startswith('/') and not value.startswith('//'),
                         'Invalid baseline inventory path')
        path = baseline.safe_relative(value)
        contract.require(value == '/' + str(path) and value not in all_names,
                         'Invalid or duplicate baseline inventory path')
        all_names.add(value)
        managed = value.startswith('/__/')
        contract.require(row.get('managed') is managed, 'Invalid Firebase managed classification')
        if not managed:
            live_public[str(path)] = (row.get('rawSha256'), row.get('rawBytes'))
    seal = baseline.read(base / 'seal-report.json')
    seal_rows = seal['files']
    seal_public = {str(baseline.safe_relative(row['path'])): (row['sha256'], row['bytes']) for row in seal_rows}
    contract.require(len(seal_public) == len(seal_rows) and live_public == seal_public,
                     'Baseline public bytes differ from live receipt')
    contract.require(receipt.get('catalogSha256') == seal.get('catalogSha256')
                     and receipt.get('firebaseJsonSha256') == baseline.digest(base / 'firebase.json'),
                     'Baseline catalog or Firebase config differs from live receipt')



class _PageDependencies(HTMLParser):
    """A conservative static-page subset: no executable or implicit fetches."""
    def __init__(self, *, page_path=Path('index.html'), source_url=None):
        super().__init__(convert_charrefs=True)
        self.paths = set()
        self.links = set()
        self.page_path = page_path
        self.source_url = source_url
        self.in_style = False

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        contract.require(tag not in ('script', 'iframe', 'object', 'embed', 'link', 'form', 'base'),
                         'Unsupported executable or external page dependency')
        contract.require(not any(k.startswith('on') or k in ('srcset', 'action', 'formaction', 'xlink:href', 'data', 'background', 'srcdoc', 'ping')
                                 for k, _ in attributes), 'Unsupported page dependency attribute')
        contract.require(not (tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh'),
                         'Unsupported page refresh')
        self.in_style = tag == 'style' or self.in_style
        for key, value in attributes:
            value = value or ''
            if key == 'style':
                contract.require('url(' not in value.lower() and '@import' not in value.lower()
                                 and chr(92) not in value, 'Unsupported CSS dependency')
            if key in ('src', 'poster'):
                contract.require(value.startswith('/') and not value.startswith('//')
                                 and not urlsplit(value).query and not urlsplit(value).fragment,
                                 'Page dependency must use a root-relative asset')
                self.paths.add(baseline.safe_relative(value))
            if key == 'href':
                contract.require(tag == 'a' and value == value.strip(), 'Unsupported page link')
                parsed = urlsplit(value)
                if parsed.scheme or parsed.netloc:
                    contract.require(self.source_url is not None and value == self.source_url,
                                     'External page link is not the verified source URL')
                elif parsed.path:
                    contract.require(not parsed.query and '%' not in parsed.path and chr(92) not in parsed.path
                                     and '..' not in Path(parsed.path).parts,
                                     'Unsafe internal page link')
                    resolved = urlsplit(urljoin('https://candidate.invalid/' + str(self.page_path), value))
                    contract.require(resolved.hostname == 'candidate.invalid', 'Unsafe internal page link')
                    self.links.add(baseline.safe_relative(resolved.path))

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            contract.require('url(' not in data.lower() and '@import' not in data.lower()
                             and chr(92) not in data, 'Unsupported CSS dependency')


def verify_page_links(parser, allowed_paths):
    contract.require(parser.links <= allowed_paths, 'Internal page link has no file in the candidate')


def verify_english_reference(value, page, releases, public):
    contract.require(value.get('schemaVersion') == 'sermon-published-english-reference-v1'
                     and value.get('pageId') == page['id']
                     and value.get('sourceIdentitySha256') == page['sourceIdentitySha256']
                     and value.get('sourceMediaSha256') == page['sourceMediaSha256']
                     and value.get('reviewState') == 'human_approved'
                     and set(value.get('targets', {})) == set(page['targets']),
                     'English reference identity differs')
    for locale, evidence in value['targets'].items():
        target = page['targets'][locale]
        release = releases[locale]
        assets = {asset['role']: asset for asset in release['assets']}
        contract.require(evidence.get('releasePackageJsonSha256') == target['releasePackageJsonSha256']
                         and evidence.get('contentSha256') == assets['content']['sha256']
                         and evidence.get('captionsSha256') == assets['captions']['sha256'],
                         'English reference locale binding differs')
        content = baseline.read(public / baseline.safe_relative(assets['content']['path']))
        captions = baseline.read(public / baseline.safe_relative(assets['captions']['path']))
        blocks, groups, cues = evidence.get('blocks'), content.get('cues'), captions.get('cues')
        contract.require(isinstance(blocks, list) and blocks and isinstance(groups, list)
                         and isinstance(cues, list) and len(blocks) == len(groups) == len(cues),
                         'English reference group count differs')
        identities = []
        for block, group, cue in zip(blocks, groups, cues):
            group_id, units = group.get('textGroupId'), group.get('sourceUnitIds')
            contract.require(isinstance(group_id, str) and group_id and isinstance(units, list) and units
                             and all(isinstance(unit, str) and unit for unit in units)
                             and block.get('textGroupId') == cue.get('textGroupId') == group_id
                             and block.get('sourceUnitIds') == cue.get('sourceUnitIds') == units
                             and isinstance(block.get('english'), str) and block['english'].strip(),
                             'English reference group mapping differs')
            identities.append(group_id)
        contract.require(len(identities) == len(set(identities)), 'Duplicate English reference groups')



def prepare(base, source, page_id, out):
    base, source, out = (Path(p).resolve() for p in (base, source, out))
    contract.require(len({base, source, out}) == 3 and not out.exists()
                     and not any(a.is_relative_to(b) for a, b in
                                 ((out, base), (base, out), (out, source), (source, out))),
                     'Unsafe candidate path')
    receipt = baseline.read(base / 'baseline-receipt.json')
    target = baseline.hosting_target('dev')
    contract.require(receipt.get('status') == 'complete_verified_not_deployed'
                     and all(receipt.get(k) == target[k] for k in ('project', 'site', 'origin')),
                     'A verified Dev baseline is required')
    contract.validate_catalog_snapshot(base)
    verify_live_baseline(base, receipt)
    contract.validate_catalog_snapshot(source)
    source_catalog = baseline.read(source / 'public/multilingual-v5.json')
    candidates = [p for p in source_catalog['pages'] if p['id'] == page_id]
    contract.require(len(candidates) == 1 and candidates[0].get('sourceMode') == 'single_source',
                     'Expected exactly one sealed single-source page')
    page = copy.deepcopy(candidates[0])
    # Copying an absolute production video redirect into Dev is not an environment migration.
    contract.require(not page.get('videoDelivery') and all(not t.get('videoDelivery')
                     for t in page['targets'].values()), 'Video delivery requires a separate Dev migration')
    public, source_public = base / 'public', source / 'public'
    current = baseline.read(public / 'multilingual-v5.json')
    contract.require(not any(p['id'] == page_id for p in current['pages']), 'Page already exists in Dev')
    before = {v: baseline.read(public / name) for v, name in contract.CATALOG_FILES.items()}
    for value in before.values():
        contract.require(not any(p['id'] == page_id for p in value['pages']), 'Page already exists in a legacy catalog')
    merged = copy.deepcopy(current)
    merged['pages'].append(page)
    merged['generatedAt'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    contract.validate_catalog_schema(merged)
    v4 = contract.project_legacy_catalog_v4(merged)
    v3 = contract.project_human_catalog(v4)
    new_catalogs = {contract.CATALOG_V5: merged, contract.CATALOG_V4: v4, contract.CATALOG_V3: v3}
    for version, value in new_catalogs.items():
        old = before[version]
        contract.require(value['defaultPageId'] == old['defaultPageId']
                         and [p for p in value['pages'] if p['id'] != page_id] == old['pages'],
                         'Legacy projection would change an existing page or default')
    rows = {r['path'].lstrip('/'): r for r in baseline.read(source / 'seal-report.json')['files']}
    paths, releases, page_paths = set(), {}, []
    for locale, target_row in page['targets'].items():
        release_path = baseline.safe_relative(target_row['releasePackageUrl'])
        release_file = source_public / release_path
        contract.require(release_file.is_file() and baseline.digest(release_file) == target_row['releasePackageJsonSha256'],
                         'Source release hash differs')
        release = baseline.read(release_file)
        releases[locale] = release
        contract.validate_release_schema(release)
        if release['schemaVersion'] in contract.FOUR_PRODUCT_RELEASES:
            contract.validate_release_target(release, page, locale)
        else:
            contract.validate_v2_release_target(release, page, locale)
        paths.add(release_path)
        for asset in release['assets']:
            path = baseline.safe_relative(asset['path'])
            contract.require((source_public / path).is_file() and baseline.digest(source_public / path) == asset['sha256'],
                             'Source release asset hash differs')
            paths.add(path)
            if asset['role'] == 'page':
                page_paths.append(path)
            if asset['role'] == 'content':
                contract.validate_content_target(baseline.read(source_public / path), page, locale)
        fingerprint = target_row.get('audioFingerprint')
        if fingerprint:
            audio_assets = [asset for asset in release['assets'] if asset['role'] == 'audio']
            contract.require(len(audio_assets) == 1 and fingerprint.get('pageId') == page_id
                             and fingerprint.get('sourceSha256') == page['sourceMediaSha256']
                             and fingerprint.get('trackSha256') == audio_assets[0]['sha256'],
                             'Fingerprint differs from source or audio')
            path = baseline.safe_relative(fingerprint['indexUrl'])
            contract.require((source_public / path).is_file()
                             and baseline.digest(source_public / path) == fingerprint['indexSha256'],
                             'Source fingerprint hash differs')
            paths.add(path)
    source_url = page.get('sourceUrl')
    if source_url:
        source_url_sha = hashlib.sha256(source_url.encode('utf-8')).hexdigest()
        # A URL is allowed as an external link only if every imported release binds it.
        if any(release.get('sourceIdentity', {}).get('sourceUrlHash') != source_url_sha
               for release in releases.values()):
            source_url = None
    baseline_paths = {Path(row['path'].lstrip('/')) for row in baseline.read(base / 'seal-report.json')['files']}
    for page_path in page_paths:
        parser = _PageDependencies(page_path=page_path, source_url=source_url)
        parser.feed((source_public / page_path).read_text(encoding='utf-8'))
        contract.require(parser.paths <= paths, 'Page references an asset outside the import closure')
        verify_page_links(parser, baseline_paths | paths)
    for prefix in ('english-reference', 'alignment'):
        path = Path(prefix) / (page_id + '.json')
        if (source_public / path).is_file():
            if prefix == 'english-reference':
                verify_english_reference(baseline.read(source_public / path), page, releases, source_public)
            else:
                published_alignment_catalog.bind_catalogs(source_public, page_id)
            paths.add(path)
    for path in paths:
        f, row = source_public / path, rows.get(str(path))
        contract.require(row is not None and not f.is_symlink() and f.resolve().is_relative_to(source_public)
                         and baseline.digest(f) == row['sha256'] and f.stat().st_size == row['bytes'],
                         'Source seal differs')
        existing = public / path
        contract.require(not existing.exists() or (existing.is_file() and not existing.is_symlink()
                         and baseline.digest(existing) == row['sha256']), 'Existing asset collision')
    out.mkdir(parents=True)
    try:
        shutil.copytree(public, out / 'public')
        shutil.copyfile(base / 'firebase.json', out / 'firebase.json')
        shutil.copyfile(base / 'baseline-receipt.json', out / 'baseline-receipt.json')
        imported = []
        for path in sorted(paths):
            destination = out / 'public' / path
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_public / path, destination)
                imported.append('/' + str(path))
        # Copy operations can race with local modifications. Bind the resulting
        # bytes to the immutable receipts, rather than sealing whatever was copied.
        for row in receipt['rows']:
            if row['managed']:
                continue
            file = out / 'public' / baseline.safe_relative(row['path'])
            contract.require(file.is_file() and baseline.digest(file) == row['rawSha256']
                             and file.stat().st_size == row['rawBytes'], 'Copied baseline asset differs from live receipt')
        for path in paths:
            file, row = out / 'public' / path, rows[str(path)]
            contract.require(file.is_file() and baseline.digest(file) == row['sha256']
                             and file.stat().st_size == row['bytes'], 'Copied imported asset differs from source seal')
        for version, value in new_catalogs.items():
            path = out / 'public' / contract.CATALOG_FILES[version]
            path.unlink()
            baseline.write(path, value)
        report = {**baseline.catalog_report(out / 'public'), 'files': baseline.files_report(out / 'public')}
        baseline.write(out / 'seal-report.json', report)
        contract.validate_catalog_snapshot(out)
        baseline.write(out / 'publish-config.json', baseline.publication_config(base, out, environment='dev'))
        baseline.write(out / 'single-source-dev-overlay-plan.json', {
            'schemaVersion': 'sermon-single-source-dev-overlay-v1', 'status': 'prepared_not_deployed',
            'pageId': page_id, 'sourceIdentitySha256': page['sourceIdentitySha256'],
            'sourceMediaSha256': page['sourceMediaSha256'], 'importedPaths': imported,
            'devHttpVerification': 'not_run', 'sourceHttpEvidence': 'original_source_only',
            'defaultPageId': current['defaultPageId'], 'baselineVersion': receipt['baselineVersion']})
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise
    return {'status': 'prepared_not_deployed', 'pageId': page_id,
            'publishConfig': str(out / 'publish-config.json'), 'importedFiles': len(imported)}
