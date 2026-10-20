"""Acquire a complete live-bound Hosting snapshot or isolated Dev overlay.

No model API and no deployment are performed. A publish config is consumed only
by guarded_hosting_publish, which acquires the shared generation-fenced lease.
Firebase-managed /__/ resources are recorded separately and never uploaded.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import copy
import gzip
import hashlib
import json
import re
from pathlib import Path
import shutil
import struct
import zlib
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import backend as _delivery
from . import contract
from . import publication as publisher


def _builder():
    # The four-product builder moves into delivery/ in D2; until then the host supplies it.
    return _delivery.current().unmoved.app_release()

PROJECT = SITE = 'ai-for-god-sermon-audio-dev'
ORIGIN = 'https://' + SITE + '.web.app'
LEASE_BUCKET = 'ai-for-god-sermon-media-dev'


def hosting_target(environment):
    """Fixed deployment identities; simulations continue to default to Dev."""
    contract.require(environment in ('dev', 'production'), 'Unknown Hosting environment')
    if environment == 'production':
        return {'project': 'ai-for-god-caption-dev', 'site': 'ai-for-god-sermon-audio',
                'origin': 'https://ai-for-god-sermon-audio.web.app',
                'channel': 'production_web', 'lease_bucket': 'ai-for-god-sermon-media-prod'}
    return {'project': PROJECT, 'site': SITE, 'origin': ORIGIN,
            'channel': 'dev', 'lease_bucket': LEASE_BUCKET}


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')


def safe_relative(value):
    path = Path(value.lstrip('/'))
    contract.require(not path.is_absolute() and '..' not in path.parts and str(path) not in ('', '.'), 'Unsafe public path')
    return path


def ensure_video_redirect(config, delivery):
    """Add one exact immutable video redirect without depending on legacy adapters."""
    value = copy.deepcopy(config)
    hosting = value.get('hosting')
    contract.require(isinstance(hosting, dict) and hosting.get('public') == 'public',
                     'Expected complete Hosting configuration')
    expected = {'source': delivery['canonicalUrl'], 'destination': delivery['storageUrl'], 'type': 302}
    matches = [row for row in hosting.setdefault('redirects', [])
               if row.get('source') == delivery['canonicalUrl']]
    contract.require(not matches or matches == [expected], 'Video redirect conflicts with target edition')
    added = not matches
    if added:
        hosting['redirects'].append(expected)
    csp = [header for rule in hosting.get('headers', []) for header in rule.get('headers', [])
           if header.get('key', '').lower() == 'content-security-policy']
    contract.require(len(csp) == 1, 'Expected exactly one site-wide media CSP')
    text = csp[0].get('value', '')
    if "media-src 'self' blob:" in text:
        csp[0]['value'] = text.replace("media-src 'self' blob:",
                                      "media-src 'self' https://storage.googleapis.com blob:")
    else:
        contract.require("media-src 'self' https://storage.googleapis.com blob:" in text,
                         'Unexpected CSP media-src; review before migration')
    return value, added


def require_video_environment(delivery, environment):
    bucket = 'prod' if environment == 'production' else 'dev'
    contract.require(environment in ('production', 'dev')
                     and delivery['storageUrl'].startswith(
                         f'https://storage.googleapis.com/ai-for-god-sermon-media-{bucket}/'),
                     'Target video bucket differs from publication environment')


def firebase_config(config, *, environment='dev'):
    """Lossless mapping of supported API VersionConfig to Firebase CLI keys."""
    allowed = {'headers', 'redirects', 'rewrites', 'cleanUrls', 'trailingSlashBehavior'}
    contract.require(set(config) <= allowed, 'Unsupported live Hosting config; preserve explicitly before proceeding')
    hosting = {'site': hosting_target(environment)['site'], 'public': 'public', 'ignore': ['firebase.json', '**/.*', '**/node_modules/**']}
    if 'headers' in config:
        hosting['headers'] = [{'source': row['glob'], 'headers': [{'key': k, 'value': v} for k, v in row['headers'].items()]} for row in config['headers']]
    if 'redirects' in config:
        hosting['redirects'] = []
        for row in config['redirects']:
            contract.require(set(row) == {'glob', 'location', 'statusCode'}, 'Unsupported live redirect')
            hosting['redirects'].append({'source': row['glob'], 'destination': row['location'], 'type': row['statusCode']})
    if 'rewrites' in config:
        hosting['rewrites'] = []
        for row in config['rewrites']:
            destinations = set(row) & {'path', 'run', 'function'}
            contract.require(set(row) <= {'glob', 'path', 'run', 'function'}
                             and 'glob' in row and len(destinations) == 1,
                             'Unsupported live rewrite')
            kind = next(iter(destinations))
            contract.require(isinstance(row[kind], (str, dict)) and bool(row[kind]),
                             'Invalid live rewrite destination')
            hosting['rewrites'].append({'source': row['glob'],
                                       'destination' if kind == 'path' else kind: row[kind]})
    if 'cleanUrls' in config:
        hosting['cleanUrls'] = config['cleanUrls']
    if 'trailingSlashBehavior' in config:
        contract.require(config['trailingSlashBehavior'] in ('ADD', 'REMOVE', 'TRAILING_SLASH_BEHAVIOR_UNSPECIFIED'), 'Unknown trailing-slash behavior')
        if config['trailingSlashBehavior'] != 'TRAILING_SLASH_BEHAVIOR_UNSPECIFIED':
            hosting['trailingSlash'] = config['trailingSlashBehavior'] == 'ADD'
    return {'hosting': hosting}


def config_semantics(config):
    value = json.loads(json.dumps(config))
    for row in value.get('hosting', {}).get('headers', []):
        row['headers'] = sorted(row['headers'], key=lambda h: h['key'])
    return value


def catalog_report(public):
    """All catalog hashes present in a complete Hosting snapshot."""
    public = Path(public)
    v4 = public / contract.CATALOG_FILES[contract.CATALOG_V4]
    v5 = public / contract.CATALOG_FILES[contract.CATALOG_V5]
    return {'catalogSha256': digest(public / 'multilingual-v3.json'),
            **({'catalogV4Sha256': digest(v4)} if v4.exists() else {}),
            **({'catalogV5Sha256': digest(v5)} if v5.exists() else {})}


def files_report(public):
    return [{'path': '/' + str(p.relative_to(public)), 'sha256': digest(p), 'bytes': p.stat().st_size}
            for p in sorted(public.rglob('*')) if p.is_file()]


def firebase_cli_gzip_hashes(path):
    """Join identity responses to exact deterministic CLI gzip version hashes.

    zlib gzip's OS byte differs across CLI hosts. Every accepted value still
    requires the complete compressed byte hash to match the frozen API row.
    Streaming avoids loading large media into memory.
    """
    hashes = [hashlib.sha256(bytes.fromhex('1f8b08000000000002') + bytes([os_byte]))
              for os_byte in (0, 3, 19, 255)]
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    crc, size = 0, 0
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            crc = zlib.crc32(chunk, crc)
            size += len(chunk)
            compressed = compressor.compress(chunk)
            for value in hashes:
                value.update(compressed)
    trailer = compressor.flush() + struct.pack('<II', crc & 0xffffffff, size & 0xffffffff)
    for value in hashes:
        value.update(trailer)
    return {value.hexdigest() for value in hashes}


def baseline(out, *, cache_public=None, cache_receipt=None, environment='dev'):
    out = Path(out).resolve()
    contract.require(not out.exists(), 'Use a new baseline output directory')
    deployment_target = hosting_target(environment)
    site, origin = deployment_target['site'], deployment_target['origin']
    request = publisher.authenticated_transport()
    version = publisher.live_version(request, site)
    contract.require(version.startswith('sites/' + site + '/versions/'), 'Live version target differs')
    detail = request('GET', 'https://firebasehosting.googleapis.com/v1beta1/' + version)
    contract.require(detail.get('status') == 'FINALIZED', 'Live version is not finalized')
    rows = []
    token = None
    while True:
        url = 'https://firebasehosting.googleapis.com/v1beta1/' + version + '/files?pageSize=1000'
        if token:
            url += '&pageToken=' + quote(token, safe='')
        page = request('GET', url)
        rows.extend(page.get('files', []))
        token = page.get('nextPageToken')
        if not token:
            break
    contract.require(rows and len({r['path'] for r in rows}) == len(rows) and all(r.get('status') == 'ACTIVE' for r in rows), 'Invalid live file inventory')
    config = firebase_config(detail.get('config', {}), environment=environment)
    cached = {}
    if cache_receipt:
        contract.require(cache_public is not None, 'Cache public root is required')
        prior = read(cache_receipt)
        for row in prior.get('rows', []):
            cached[row['path']] = row
    out.mkdir(parents=True)
    write(out / 'live-version.json', detail)
    write(out / 'live-version-files.json', {'version': version, 'files': rows})
    write(out / 'firebase.json', config)
    public = out / 'public'
    public.mkdir()

    def materialize(row):
        relative = safe_relative(row['path'])
        managed = row['path'].startswith('/__/')
        target = out / 'managed-reference' / relative if managed else public / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        prior = cached.get(row['path'])
        cached_path = Path(cache_public) / relative if cache_public else None
        if (not managed and prior and prior.get('liveGzipSha256', prior.get('gzipSha256')) == row['hash']
                and cached_path.is_file() and not cached_path.is_symlink()
                and digest(cached_path) == prior.get('rawSha256') and cached_path.stat().st_size == prior.get('rawBytes')):
            shutil.copyfile(cached_path, target)
            mode = 'verified_cached_bytes_live_version_hash_join'
            raw_sha = prior['rawSha256']
        else:
            compressed = target.with_suffix(target.suffix + '.download')
            # A file of a version deployed seconds ago may 404 or still serve the previous bytes.
            return publisher.await_propagation(lambda: fetch(row, relative, target, compressed, managed))
        return {'path': row['path'], 'rawSha256': raw_sha, 'rawBytes': target.stat().st_size,
                'liveGzipSha256': row['hash'], 'sourceKind': mode, 'managed': managed}

    def fetch(row, relative, target, compressed, managed):
        for leftover in (compressed, target):
            leftover.unlink(missing_ok=True)
        h = hashlib.sha256()
        with urlopen(Request(origin + '/' + quote(str(relative), safe='/'), headers={'Accept-Encoding': 'gzip', 'Cache-Control': 'no-cache'}), timeout=publisher.remaining_read_timeout(120)) as response:
            contract.require(response.status == 200, 'Live file GET failed')
            encoding = response.headers.get('Content-Encoding')
            etag = response.headers.get('Etag')
            with compressed.open('xb') as stream:
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    publisher.remaining_read_timeout(120)
                    h.update(chunk)
                    stream.write(chunk)
        if encoding == 'gzip':
            contract.require(h.hexdigest() == row['hash'], 'Live file no longer matches frozen version: ' + row['path'])
            with gzip.open(compressed, 'rb') as source, target.open('xb') as dest:
                shutil.copyfileobj(source, dest)
            compressed.unlink()
        else:
            contract.require(encoding in (None, 'identity'), 'Unsupported live content encoding')
            contract.require(etag == '"' + row['hash'] + '"'
                             and row['hash'] in firebase_cli_gzip_hashes(compressed),
                             'Identity response no longer matches frozen gzip version: ' + row['path'])
            compressed.rename(target)
        mode = ('live_get_version_hash_verified' if encoding == 'gzip'
                else 'live_get_identity_exact_gzip_version_hash_reconstructed')
        raw_sha = digest(target)
        return {'path': row['path'], 'rawSha256': raw_sha, 'rawBytes': target.stat().st_size,
                'liveGzipSha256': row['hash'], 'sourceKind': mode, 'managed': managed}

    with ThreadPoolExecutor(max_workers=6) as pool:
        verified = list(pool.map(materialize, rows))
    contract.require(publisher.live_version(request, site) == version, 'Live version changed during baseline acquisition')
    report = {**catalog_report(public), 'files': files_report(public)}
    write(out / 'seal-report.json', report)
    contract.validate_catalog_snapshot(out)
    receipt = {'schemaVersion': ('sermon-dev-simulated-baseline-v1' if environment == 'dev'
                                else 'sermon-production-live-baseline-v1'), 'status': 'complete_verified_not_deployed',
               'checkedAt': datetime.now(timezone.utc).isoformat(),
               **{key: deployment_target[key] for key in ('project', 'site', 'origin', 'channel')},
               'environment': environment,
               'baselineVersion': version, 'catalogSha256': report['catalogSha256'], 'liveConfig': detail.get('config', {}),
               'firebaseJsonSha256': digest(out / 'firebase.json'), 'configSemanticEqual': config_semantics(config) == config_semantics(firebase_config(detail.get('config', {}), environment=environment)), 'liveFileCount': len(rows),
               'publicFileCount': len(report['files']), 'managedFileCount': sum(r['managed'] for r in verified),
               'rows': verified, 'modelCalls': 0, 'deployment': 'not_started'}
    write(out / 'baseline-receipt.json', receipt)
    return {k: receipt[k] for k in ('status', 'baselineVersion', 'liveFileCount', 'publicFileCount', 'managedFileCount')}


def publication_config(base, out, *, environment='dev'):
    target = hosting_target(environment)
    receipt = read(base / 'baseline-receipt.json')
    contract.require(all(receipt.get(k) == target[k] for k in ('project', 'site', 'origin')),
                     'Baseline Hosting target differs')
    expected_intent = {**{k: target[k] for k in ('project', 'site', 'origin', 'channel')},
                       'environment': environment}
    version = receipt['baselineVersion']
    attempt = base / 'deployment-attempt-v2.json'
    if attempt.exists():
        deployed = read(attempt)
        prior_config = base / 'publish-config.json'
        expected_version = read(prior_config)['baseline_version'] if prior_config.exists() else version
        contract.require(deployed.get('status') == 'deployed' and deployed.get('newVersion')
                         and all(deployed.get('intent', {}).get(k) == v for k, v in
                                 expected_intent.items())
                         and deployed.get('baselineVersion') == expected_version
                         and deployed.get('catalogSha256') == digest(base / 'public/multilingual-v3.json'),
                         'Prior publication remains uncertain or differs from baseline')
        version = deployed['newVersion']
    intent = {'schemaVersion': 'sermon-release-intent-v1', **expected_intent}
    routes = {environment: {**{k: target[k] for k in ('project', 'site', 'origin')},
                           'channels': ['dev', 'beta'] if environment == 'dev' else ['production_web']}}
    return {'snapshot': str(out), 'intent': intent, 'routes': routes,
            'baseline_version': version, 'baseline_catalog_sha': digest(base / 'public/multilingual-v3.json'),
            'baseline_catalog_v4_sha': catalog_report(base / 'public').get('catalogV4Sha256'),
            'baseline_catalog_v5_sha': catalog_report(base / 'public').get('catalogV5Sha256'),
            'lease_bucket': target['lease_bucket']}


def bound_release_plan(baseline_path, prepared_path):
    """Build the seal/merge contract from verified bytes, not raw JSON hashes."""
    builder = _builder()
    base, prepared = Path(baseline_path).resolve(), Path(prepared_path).resolve()
    catalog = contract.validate_catalog_snapshot(base)
    manifest, _ = builder.verified_assets(prepared)
    receipt = read(base / 'baseline-receipt.json')
    contract.require(receipt.get('status') == 'complete_verified_not_deployed'
                     and all(receipt.get(k) == v for k, v in
                             {'project': PROJECT, 'site': SITE, 'origin': ORIGIN}.items())
                     and receipt.get('catalogSha256') == digest(base / 'public/multilingual-v3.json'),
                     'Verified Dev baseline receipt required')
    page_id = manifest['pageId']
    contract.require(isinstance(page_id, str) and re.fullmatch(r'(?:mockup|dryrun|dev)-[A-Za-z0-9][A-Za-z0-9_-]{0,139}', page_id), 'Isolated test page required')
    contract.require(page_id not in {page['id'] for page in catalog['pages']}, 'Simulation page ID already exists; use a new run ID')
    locales = sorted(manifest['releases'])
    contract.require(set(locales) == {'zh-Hans', 'ko', 'es'}, 'Three locale test coverage required')
    config = publication_config(base, base)
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1',
            'baselineCatalogSha256': contract.sha(catalog),
            'baselineVersion': config['baseline_version'], 'pageId': page_id,
            'locales': locales, 'requiredLocales': locales, 'mode': 'joined'}
    # Exercise the same contract used by seal before handing a plan to it.
    candidate = {'schemaVersion': catalog['schemaVersion'], 'generatedAt': catalog['generatedAt'],
                 'defaultPageId': page_id, 'pages': [{
                     'id': page_id, 'date': manifest['date'], 'title': manifest['title'],
                     'sourceLocale': 'en', 'sourceIdentitySha256': manifest['englishSourcePackageJsonSha256'],
                     'defaultTargetLocale': 'zh-Hans', 'targets': {
                         locale: {'releasePackageUrl': item['releasePath'],
                                  'releasePackageJsonSha256': item['releaseSha256']}
                         for locale, item in manifest['releases'].items()}}]}
    merged = contract.merge_catalog(catalog, candidate, plan)
    contract.require(merged['defaultPageId'] == catalog['defaultPageId']
                     and merged['pages'][:-1] == catalog['pages'], 'Release plan changed default or siblings')
    return plan


def release_plan(baseline_path, prepared_path, out):
    out = Path(out).resolve()
    contract.require(not out.exists(), 'Release plan output already exists')
    plan = bound_release_plan(baseline_path, prepared_path)
    write(out, plan)
    return {'status': 'prepared_not_deployed', 'releasePlan': str(out), **plan}


def asset_first(baseline_path, prepared, out, source_video=None):
    builder = _builder()
    runtime_root = builder.runtime_web_root()
    runtime_files = builder.runtime_web_files(runtime_root)
    base, prepared, out = map(lambda p: Path(p).resolve(), (baseline_path, prepared, out))
    contract.require(not out.exists() and not out.is_relative_to(base) and not out.is_relative_to(prepared), 'Unsafe asset-first output')
    contract.validate_catalog_snapshot(base)
    manifest, assets = builder.verified_assets(prepared)
    contract.require(set(manifest['releases']) == {'zh-Hans', 'ko', 'es'}, 'Three locales required')
    receipt = read(base / 'baseline-receipt.json')
    contract.require(receipt['project'] == PROJECT and receipt['site'] == SITE and receipt['origin'] == ORIGIN, 'Dev target only')
    out.mkdir(parents=True)
    shutil.copytree(base / 'public', out / 'public')
    shutil.copyfile(base / 'firebase.json', out / 'firebase.json')
    shutil.copyfile(base / 'baseline-receipt.json', out / 'baseline-receipt.json')
    changed = []
    for row in assets:
        relative = safe_relative(row['path'])
        contract.require(relative.parts[0] != '__', 'Cannot override managed files')
        src, target = prepared / 'public' / relative, out / 'public' / relative
        contract.require(digest(src) == row['sha256'], 'Prepared asset changed')
        if target.exists():
            contract.require(str(relative) in runtime_files or digest(target) == row['sha256'], 'Existing asset collision')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or digest(target) != row['sha256']:
            shutil.copyfile(src, target)
            changed.append('/' + str(relative))
    if source_video:
        source_video = Path(source_video).resolve()
        source_sha = digest(source_video)
        relative = Path('media') / manifest['pageId'] / 'source.mp4'
        contents = [read(prepared / 'public' / safe_relative(row['path'])) for row in assets if row['role'] == 'content']
        contract.require(len(contents) == 3 and all(c['sourceVideoUrl'] == '/' + str(relative) and c['sourceMediaSha256'] == source_sha for c in contents), 'Source-video binding differs from prepared content')
        target = out / 'public' / relative
        contract.require(not target.exists(), 'Source-video collision')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_video, target)
        changed.append('/' + str(relative))
    contract.require(digest(out / 'public/multilingual-v3.json') == receipt['catalogSha256'], 'Asset-first catalog changed')
    report = {**catalog_report(out / 'public'), 'files': files_report(out / 'public')}
    write(out / 'seal-report.json', report)
    contract.validate_catalog_snapshot(out)
    write(out / 'publish-config.json', publication_config(base, out))
    write(out / 'asset-first-plan.json', {'status': 'prepared_not_deployed', 'pageId': manifest['pageId'], 'assets': assets,
          'changedPaths': changed, 'catalogUnchanged': True, 'httpVerification': 'not_run', 'productionEligible': False,
          'managedFilesPreservedByFirebase': [r for r in receipt['rows'] if r['managed']], 'modelCalls': 0})
    return {'status': 'prepared_not_deployed', 'publishConfig': str(out / 'publish-config.json'), 'assetCount': len(assets)}


def with_simulated_page(v4, catalog, page_id):
    """Add the v3 catalog's new page to v4 after the same predecessor, so v3 stays v4's human-only projection."""
    v4 = copy.deepcopy(v4)
    ids = [page['id'] for page in catalog['pages']]
    index = ids.index(page_id)
    position = 0 if index == 0 else [page['id'] for page in v4['pages']].index(ids[index - 1]) + 1
    v4['pages'].insert(position, copy.deepcopy(catalog['pages'][index]))
    v4['generatedAt'] = catalog['generatedAt']
    contract.require(contract.project_human_catalog(v4) == catalog, 'Simulated page breaks the v4 projection')
    return v4


def machine_checked_overlay(baseline_path, overlay_public, catalog_path, out):
    """Overlay one isolated machine-checked test page from a sealed v4 catalog.

    Machine-checked targets exist only in v4; the human-only v3 projection must be
    unchanged, so only the v4 catalog and the page's own assets change."""
    builder = _builder()
    runtime_root = builder.runtime_web_root()
    runtime_files = builder.runtime_web_files(runtime_root)
    base, incoming, out = map(lambda p: Path(p).resolve(), (baseline_path, overlay_public, out))
    contract.require(not out.exists() and not out.is_relative_to(base) and not out.is_relative_to(incoming), 'Unsafe overlay output')
    before_v3 = contract.validate_catalog_snapshot(base)
    receipt = read(base / 'baseline-receipt.json')
    contract.require(receipt['project'] == PROJECT and receipt['site'] == SITE and receipt['origin'] == ORIGIN, 'Dev target only')
    before = contract.snapshot_catalog_v4(base)
    catalog = read(catalog_path)
    contract.require(catalog['schemaVersion'] == contract.CATALOG_V4, 'Machine-checked overlay needs the sealed v4 catalog')
    old_pages = {p['id']: p for p in before['pages']}
    new_pages = {p['id']: p for p in catalog['pages']}
    contract.require(len(new_pages) == len(catalog['pages']) and set(old_pages) <= set(new_pages), 'Missing or duplicate sibling pages')
    added = [p for p in catalog['pages'] if p['id'] not in old_pages]
    contract.require(len(added) == 1 and added[0]['id'].startswith(('mockup-', 'dryrun-', 'dev-')), 'Exactly one isolated test page is required')
    contract.require(set(added[0]['targets']) == {'zh-Hans', 'ko', 'es'}
                     and all(t.get('contentStatus') == t.get('audioStatus') == contract.MACHINE_CHECKED
                             for t in added[0]['targets'].values()), 'Three machine-checked locale targets required')
    # Real (formal) content is diagnostic, never a simulation: readers refuse formal content on a
    # simulationOnly page, and a diagnostic page is never the default.
    added[0].update(diagnosticOnly=True)
    for target in added[0]['targets'].values():
        target.update(diagnosticOnly=True)
    catalog['defaultPageId'] = before['defaultPageId']
    # v3 stays byte-identical, so v4 keeps the generation time it projects to.
    catalog['generatedAt'] = before_v3['generatedAt']
    contract.require(all(new_pages[k] == v for k, v in old_pages.items()), 'Existing page changed')
    contract.require(contract.project_human_catalog(catalog) == before_v3, 'Machine-checked test page would change the v3 catalog')
    out.mkdir(parents=True)
    shutil.copytree(base / 'public', out / 'public')
    shutil.copyfile(base / 'firebase.json', out / 'firebase.json')
    changed = []
    for src in sorted(incoming.rglob('*')):
        if not src.is_file():
            continue
        relative = src.relative_to(incoming)
        contract.require(not src.is_symlink() and relative.parts[0] != '__', 'Unsafe or managed overlay file')
        if str(relative) in contract.CATALOG_FILES.values():
            continue
        target = out / 'public' / relative
        if target.exists() and digest(target) == digest(src):
            continue
        contract.require(not target.exists() or str(relative) in runtime_files, 'Existing immutable resource overwrite refused: ' + str(relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        changed.append('/' + str(relative))
    v4_path = out / 'public' / contract.CATALOG_FILES[contract.CATALOG_V4]
    if v4_path.exists():
        v4_path.unlink()
    write(v4_path, catalog)
    report = {**catalog_report(out / 'public'), 'files': files_report(out / 'public')}
    write(out / 'seal-report.json', report)
    contract.validate_catalog_snapshot(out)
    publish_config = publication_config(base, out)
    shutil.copyfile(base / 'baseline-receipt.json', out / 'baseline-receipt.json')
    write(out / 'publish-config.json', publish_config)
    write(out / 'simulation-publication-plan.json', {'schemaVersion': 'sermon-dev-simulated-publication-plan-v1',
          'publication': 'not_started', 'productionEligible': False, 'pageId': added[0]['id'], 'contentMode': 'machine_checked',
          'changedPaths': changed + ['/multilingual-v4.json'], 'originalDefaultPageId': before['defaultPageId'],
          'siblingsPreserved': len(old_pages), 'managedFilesPreservedByFirebase': [r for r in receipt['rows'] if r['managed']],
          'hostingConfigPreservedSha256': digest(out / 'firebase.json'), 'modelCalls': 0})
    return {'status': 'prepared_not_deployed', 'publishConfig': str(out / 'publish-config.json'), 'pageId': added[0]['id']}


def mixed_source_catalog_overlay(baseline_path, catalog_path, release_plan_path, out, *, environment='production'):
    """Atomically stage mixed catalogs, trusted runtime and edition video redirects."""
    base, catalog_path, plan_path, out = map(Path, (baseline_path, catalog_path, release_plan_path, out))
    base, catalog_path, plan_path, out = (path.resolve() for path in (base, catalog_path, plan_path, out))
    contract.require(not out.exists() and not out.is_relative_to(base) and not base.is_relative_to(out),
                     'Unsafe mixed-source overlay output')
    contract.validate_catalog_snapshot(base)
    candidate = contract.validate_catalog_schema(read(catalog_path))
    contract.require(candidate['schemaVersion'] == contract.CATALOG_V5 and len(candidate['pages']) == 1
                     and candidate['pages'][0]['sourceMode'] == 'per_target',
                     'Mixed-source overlay needs one per-target family page')
    plan = read(plan_path)
    current = contract.snapshot_catalog_v5(base)
    merged = contract.merge_catalog(current, candidate, plan)
    v4 = contract.project_legacy_catalog_v4(merged)
    v3 = contract.project_human_catalog(v4)
    out.mkdir(parents=True)
    try:
        return _stage_mixed_source_overlay(base, out, candidate, current, merged, v4, v3, environment)
    except BaseException:
        # out did not exist before this call; leave no partial candidate behind, so a
        # retry with the same path works and nothing half-built looks immutable.
        shutil.rmtree(out, ignore_errors=True)
        raise


def _stage_mixed_source_overlay(base, out, candidate, current, merged, v4, v3, environment):
    shutil.copytree(base / 'public', out / 'public')
    shutil.copyfile(base / 'baseline-receipt.json', out / 'baseline-receipt.json')
    public = out / 'public'
    changed = []
    runtime_root = _builder().runtime_web_root()
    runtime_files = _builder().runtime_web_files(runtime_root)
    for name in runtime_files:
        source, target = runtime_root / name, public / name
        contract.require(source.is_file() and not source.is_symlink(), 'Trusted runtime file is missing: ' + name)
        if target.exists() and digest(target) == digest(source):
            continue
        contract.require(not target.exists() or (not target.is_symlink() and target.resolve().is_relative_to(public)),
                         'Unsafe runtime replacement: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        changed.append('/' + name)

    config = read(base / 'firebase.json')
    videos = {}
    for target in candidate['pages'][0]['targets'].values():
        delivery = target['videoDelivery']
        canonical = delivery['canonicalUrl']
        contract.require(canonical not in videos or videos[canonical] == delivery,
                         'Mixed-source targets disagree on one video redirect')
        videos[canonical] = delivery
    for delivery in videos.values():
        require_video_environment(delivery, environment)
        config, added = ensure_video_redirect(config, delivery)
        if added:
            changed.append('/firebase.json#redirect:' + delivery['canonicalUrl'])
    write(out / 'firebase.json', config)
    for version, value in ((contract.CATALOG_V5, merged), (contract.CATALOG_V4, v4),
                           (contract.CATALOG_V3, v3)):
        path = public / contract.CATALOG_FILES[version]
        if path.exists():
            path.unlink()
        write(path, value)
    report = {**catalog_report(public), 'files': files_report(public)}
    write(out / 'seal-report.json', report)
    contract.validate_catalog_snapshot(out)
    write(out / 'publish-config.json', publication_config(base, out, environment=environment))
    base_public = {str(path.relative_to(base / 'public')): digest(path)
                   for path in (base / 'public').rglob('*') if path.is_file()
                   and str(path.relative_to(base / 'public')) not in runtime_files
                   and str(path.relative_to(base / 'public')) not in contract.CATALOG_FILES.values()}
    overlaid_public = {name: digest(public / name) for name in base_public}
    contract.require(base_public == overlaid_public, 'Edition asset bytes changed during mixed-source overlay')
    write(out / 'mixed-source-catalog-plan.json', {
        'schemaVersion': 'sermon-mixed-source-catalog-overlay-v1',
        'status': 'prepared_not_deployed', 'pageId': candidate['pages'][0]['id'],
        'baselineCatalogV5Sha256': contract.sha(current),
        'candidateCatalogV5Sha256': contract.sha(candidate),
        'catalogV5Sha256': report['catalogV5Sha256'],
        'catalogV4Sha256': report['catalogV4Sha256'], 'catalogSha256': report['catalogSha256'],
        'changedPaths': sorted(changed + ['/multilingual-v5.json', '/multilingual-v4.json', '/multilingual-v3.json']),
        'editionAssetsChanged': False, 'preservedEditionAssetsSha256': contract.sha(base_public),
        'runtimeFiles': sorted(runtime_files), 'firebaseConfigSha256': digest(out / 'firebase.json'),
        'publication': 'not_started'})
    return {'status': 'prepared_not_deployed', 'publishConfig': str(out / 'publish-config.json'),
            'pageId': candidate['pages'][0]['id']}


def overlay(baseline_path, overlay_public, catalog_path, out):
    builder = _builder()
    runtime_root = builder.runtime_web_root()
    runtime_files = builder.runtime_web_files(runtime_root)
    base, incoming, out = map(lambda p: Path(p).resolve(), (baseline_path, overlay_public, out))
    contract.require(not out.exists() and not out.is_relative_to(base) and not out.is_relative_to(incoming), 'Unsafe overlay output')
    before = contract.validate_catalog_snapshot(base)
    receipt = read(base / 'baseline-receipt.json')
    contract.require(receipt['project'] == PROJECT and receipt['site'] == SITE and receipt['origin'] == ORIGIN, 'Dev target only')
    catalog = read(catalog_path)
    contract.require(catalog['schemaVersion'] == before['schemaVersion'] == 'sermon-multilingual-catalog-v3', 'Wrong catalog schema')
    old_pages = {p['id']: p for p in before['pages']}
    new_pages = {p['id']: p for p in catalog['pages']}
    contract.require(len(new_pages) == len(catalog['pages']) and set(old_pages) <= set(new_pages), 'Missing or duplicate sibling pages')
    added = [p for p in catalog['pages'] if p['id'] not in old_pages]
    contract.require(len(added) == 1 and added[0]['id'].startswith(('mockup-', 'dryrun-', 'dev-')), 'Exactly one isolated test page is required')
    added[0].update(simulationOnly=True, diagnosticOnly=True)
    for target in added[0]['targets'].values():
        target.update(simulationOnly=True, diagnosticOnly=True)
    if catalog['defaultPageId'] == added[0]['id']:
        # Sealing projects v3 from a v4 catalog whose default is machine-checked; that projection moves
        # the default to the newest human page, which is this test page when it is dated after the rest.
        # Flagged now, it is never the default; the v4 projection check below proves the same choice.
        catalog['defaultPageId'] = before['defaultPageId']
    contract.require(catalog['defaultPageId'] == before['defaultPageId'] and all(new_pages[k] == v for k, v in old_pages.items()), 'Default or existing page changed')
    contract.require(set(added[0]['targets']) == {'zh-Hans', 'ko', 'es'}, 'Three locale test coverage required')
    out.mkdir(parents=True)
    shutil.copytree(base / 'public', out / 'public')
    shutil.copyfile(base / 'firebase.json', out / 'firebase.json')
    changed = []
    for src in sorted(incoming.rglob('*')):
        if not src.is_file():
            continue
        relative = src.relative_to(incoming)
        contract.require(not src.is_symlink() and relative.parts[0] != '__', 'Unsafe or managed overlay file')
        # Both catalogs are rebuilt below from the baseline and the bound v3 catalog.
        if str(relative) in contract.CATALOG_FILES.values():
            continue
        target = out / 'public' / relative
        if target.exists() and digest(target) == digest(src):
            continue
        contract.require(not target.exists() or str(relative) in runtime_files, 'Existing immutable resource overwrite refused: ' + str(relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        changed.append('/' + str(relative))
    (out / 'public/multilingual-v3.json').unlink()
    write(out / 'public/multilingual-v3.json', catalog)
    changed_catalogs = ['/multilingual-v3.json']
    v4_path = out / 'public' / contract.CATALOG_FILES[contract.CATALOG_V4]
    if v4_path.exists():
        v4 = with_simulated_page(contract.snapshot_catalog_v4(base), catalog, added[0]['id'])
        v4_path.unlink()
        write(v4_path, v4)
        changed_catalogs.append('/multilingual-v4.json')
    report = {**catalog_report(out / 'public'), 'files': files_report(out / 'public')}
    write(out / 'seal-report.json', report)
    contract.validate_catalog_snapshot(out)
    publish_config = publication_config(base, out)
    shutil.copyfile(base / 'baseline-receipt.json', out / 'baseline-receipt.json')
    write(out / 'publish-config.json', publish_config)
    write(out / 'simulation-publication-plan.json', {'schemaVersion': 'sermon-dev-simulated-publication-plan-v1',
          'publication': 'not_started', 'productionEligible': False, 'pageId': added[0]['id'], 'changedPaths': changed + changed_catalogs,
          'originalDefaultPageId': before['defaultPageId'], 'siblingsPreserved': len(old_pages), 'managedFilesPreservedByFirebase': [r for r in receipt['rows'] if r['managed']],
          'hostingConfigPreservedSha256': digest(out / 'firebase.json'), 'modelCalls': 0})
    return {'status': 'prepared_not_deployed', 'publishConfig': str(out / 'publish-config.json'), 'pageId': added[0]['id']}



def runtime_repair(baseline_path, out):
    """Refresh only the closed Web module graph, retaining the exact catalog."""
    builder = _builder()
    runtime_root = builder.runtime_web_root()
    runtime_files = builder.runtime_web_files(runtime_root)
    base, out = Path(baseline_path).resolve(), Path(out).resolve()
    contract.require(not out.exists() and not out.is_relative_to(base), 'Unsafe runtime repair output')
    contract.validate_catalog_snapshot(base)
    receipt = read(base / 'baseline-receipt.json')
    contract.require(receipt['project'] == PROJECT and receipt['site'] == SITE and receipt['origin'] == ORIGIN, 'Dev target only')
    out.mkdir(parents=True)
    shutil.copytree(base / 'public', out / 'public')
    shutil.copyfile(base / 'firebase.json', out / 'firebase.json')
    shutil.copyfile(base / 'baseline-receipt.json', out / 'baseline-receipt.json')
    changed = []
    for name in runtime_files:
        src, target = runtime_root / name, out / 'public' / name
        if not target.exists() or digest(src) != digest(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            changed.append('/' + name)
    contract.require(digest(out / 'public/multilingual-v3.json') == digest(base / 'public/multilingual-v3.json'), 'Runtime repair changed catalog')
    write(out / 'seal-report.json', {**catalog_report(out / 'public'), 'files': files_report(out / 'public')})
    contract.validate_catalog_snapshot(out)
    write(out / 'publish-config.json', publication_config(base, out))
    write(out / 'runtime-repair-plan.json', {'status': 'prepared_not_deployed', 'runtimeFiles': list(runtime_files), 'changedPaths': changed,
          'catalogUnchanged': True, 'modelCalls': 0, 'productionEligible': False})
    return {'status': 'prepared_not_deployed', 'changedPaths': changed, 'publishConfig': str(out / 'publish-config.json')}
