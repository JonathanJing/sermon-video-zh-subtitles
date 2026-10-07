"""Prepare a complete, live-bound Dev snapshot and isolated simulation overlay.

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
from urllib.parse import quote
from urllib.request import Request, urlopen

if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts import delivery_contract as contract
    from scripts import guarded_hosting_publish as publisher
except ImportError:
    import delivery_contract as contract
    import guarded_hosting_publish as publisher

PROJECT = SITE = 'ai-for-god-sermon-audio-dev'
ORIGIN = 'https://' + SITE + '.web.app'
LEASE_BUCKET = 'ai-for-god-sermon-media-dev'


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


def firebase_config(config):
    """Lossless mapping of supported API VersionConfig to Firebase CLI keys."""
    allowed = {'headers', 'redirects', 'rewrites', 'cleanUrls', 'trailingSlashBehavior'}
    contract.require(set(config) <= allowed, 'Unsupported live Hosting config; preserve explicitly before proceeding')
    hosting = {'site': SITE, 'public': 'public', 'ignore': ['firebase.json', '**/.*', '**/node_modules/**']}
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
            contract.require(set(row) == {'glob', 'path'}, 'Unsupported live rewrite')
            hosting['rewrites'].append({'source': row['glob'], 'destination': row['path']})
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
    """Both catalog hashes once the site carries v4; v3 alone before that."""
    public = Path(public)
    v4 = public / contract.CATALOG_FILES[contract.CATALOG_V4]
    return {'catalogSha256': digest(public / 'multilingual-v3.json'),
            **({'catalogV4Sha256': digest(v4)} if v4.exists() else {})}


def files_report(public):
    return [{'path': '/' + str(p.relative_to(public)), 'sha256': digest(p), 'bytes': p.stat().st_size}
            for p in sorted(public.rglob('*')) if p.is_file()]


def fetch_live_file(relative, version_hash, target):
    """Download one live file and bind it to the frozen version's gzip hash.

    Hosting records sha256(gzip(content)). A gzip response is checked byte for
    byte; small files the CDN serves uncompressed can only be bound through the
    ETag, which Hosting sets to that same version hash.
    """
    compressed = target.with_suffix(target.suffix + '.download')
    h = hashlib.sha256()
    with urlopen(Request(ORIGIN + '/' + quote(str(relative), safe='/'), headers={'Accept-Encoding': 'gzip', 'Cache-Control': 'no-cache'}), timeout=120) as response:
        contract.require(response.status == 200, 'Live file GET failed')
        encoding = response.headers.get('Content-Encoding')
        etag = (response.headers.get('ETag') or '').strip('"')
        with compressed.open('xb') as stream:
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                h.update(chunk)
                stream.write(chunk)
    if encoding == 'gzip':
        contract.require(h.hexdigest() == version_hash, 'Live file no longer matches frozen version: /' + str(relative))
        with gzip.open(compressed, 'rb') as source, target.open('xb') as dest:
            shutil.copyfileobj(source, dest)
        compressed.unlink()
        return 'live_get_version_hash_verified'
    contract.require(encoding in (None, 'identity'), 'Unsupported live content encoding')
    contract.require(etag == version_hash, 'Live file no longer matches frozen version: /' + str(relative))
    compressed.rename(target)
    return 'live_get_identity_etag_verified'


def baseline(out, *, cache_public=None, cache_receipt=None):
    out = Path(out).resolve()
    contract.require(not out.exists(), 'Use a new baseline output directory')
    request = publisher.authenticated_transport()
    version = publisher.live_version(request, SITE)
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
    config = firebase_config(detail.get('config', {}))
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
            mode = fetch_live_file(relative, row['hash'], target)
            raw_sha = digest(target)
        return {'path': row['path'], 'rawSha256': raw_sha, 'rawBytes': target.stat().st_size,
                'liveGzipSha256': row['hash'], 'sourceKind': mode, 'managed': managed}

    with ThreadPoolExecutor(max_workers=6) as pool:
        verified = list(pool.map(materialize, rows))
    contract.require(publisher.live_version(request, SITE) == version, 'Live version changed during baseline acquisition')
    report = {**catalog_report(public), 'files': files_report(public)}
    write(out / 'seal-report.json', report)
    contract.validate_catalog_snapshot(out)
    receipt = {'schemaVersion': 'sermon-dev-simulated-baseline-v1', 'status': 'complete_verified_not_deployed',
               'checkedAt': datetime.now(timezone.utc).isoformat(), 'project': PROJECT, 'site': SITE, 'origin': ORIGIN,
               'baselineVersion': version, 'catalogSha256': report['catalogSha256'], 'liveConfig': detail.get('config', {}),
               'firebaseJsonSha256': digest(out / 'firebase.json'), 'configSemanticEqual': config_semantics(config) == config_semantics(firebase_config(detail.get('config', {}))), 'liveFileCount': len(rows),
               'publicFileCount': len(report['files']), 'managedFileCount': sum(r['managed'] for r in verified),
               'rows': verified, 'modelCalls': 0, 'deployment': 'not_started'}
    write(out / 'baseline-receipt.json', receipt)
    return {k: receipt[k] for k in ('status', 'baselineVersion', 'liveFileCount', 'publicFileCount', 'managedFileCount')}


def publication_config(base, out):
    receipt = read(base / 'baseline-receipt.json')
    version = receipt['baselineVersion']
    attempt = base / 'deployment-attempt-v2.json'
    if attempt.exists():
        deployed = read(attempt)
        prior_config = base / 'publish-config.json'
        expected_version = read(prior_config)['baseline_version'] if prior_config.exists() else version
        contract.require(deployed.get('status') == 'deployed' and deployed.get('newVersion')
                         and all(deployed.get('intent', {}).get(k) == v for k, v in
                                 {'site': SITE, 'project': PROJECT, 'origin': ORIGIN, 'environment': 'dev', 'channel': 'dev'}.items())
                         and deployed.get('baselineVersion') == expected_version
                         and deployed.get('catalogSha256') == digest(base / 'public/multilingual-v3.json'),
                         'Prior publication remains uncertain or differs from baseline')
        version = deployed['newVersion']
    intent = {'schemaVersion': 'sermon-release-intent-v1', 'environment': 'dev', 'channel': 'dev', 'project': PROJECT, 'site': SITE, 'origin': ORIGIN}
    routes = {'dev': {'project': PROJECT, 'site': SITE, 'origin': ORIGIN, 'channels': ['dev', 'beta']}}
    return {'snapshot': str(out), 'intent': intent, 'routes': routes,
            'baseline_version': version, 'baseline_catalog_sha': digest(base / 'public/multilingual-v3.json'),
            'baseline_catalog_v4_sha': catalog_report(base / 'public').get('catalogV4Sha256'),
            'lease_bucket': LEASE_BUCKET}


def bound_release_plan(baseline_path, prepared_path):
    """Build the seal/merge contract from verified bytes, not raw JSON hashes."""
    from scripts import build_full_video_app_release as builder
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
    base, prepared, out = map(lambda p: Path(p).resolve(), (baseline_path, prepared, out))
    contract.require(not out.exists() and not out.is_relative_to(base) and not out.is_relative_to(prepared), 'Unsafe asset-first output')
    contract.validate_catalog_snapshot(base)
    try:
        from scripts import build_full_video_app_release as builder
    except ModuleNotFoundError:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts import build_full_video_app_release as builder
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
            contract.require(str(relative) in builder.RUNTIME_WEB_FILES or digest(target) == row['sha256'], 'Existing asset collision')
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


def overlay(baseline_path, overlay_public, catalog_path, out):
    base, incoming, out = map(lambda p: Path(p).resolve(), (baseline_path, overlay_public, out))
    contract.require(not out.exists() and not out.is_relative_to(base) and not out.is_relative_to(incoming), 'Unsafe overlay output')
    from scripts import build_full_video_app_release as builder
    before = contract.validate_catalog_snapshot(base)
    receipt = read(base / 'baseline-receipt.json')
    contract.require(receipt['project'] == PROJECT and receipt['site'] == SITE and receipt['origin'] == ORIGIN, 'Dev target only')
    catalog = read(catalog_path)
    contract.require(catalog['schemaVersion'] == before['schemaVersion'] == 'sermon-multilingual-catalog-v3', 'Wrong catalog schema')
    old_pages = {p['id']: p for p in before['pages']}
    new_pages = {p['id']: p for p in catalog['pages']}
    contract.require(len(new_pages) == len(catalog['pages']) and set(old_pages) <= set(new_pages), 'Missing or duplicate sibling pages')
    contract.require(catalog['defaultPageId'] == before['defaultPageId'] and all(new_pages[k] == v for k, v in old_pages.items()), 'Default or existing page changed')
    added = [p for p in catalog['pages'] if p['id'] not in old_pages]
    contract.require(len(added) == 1 and added[0]['id'].startswith(('mockup-', 'dryrun-', 'dev-')), 'Exactly one isolated test page is required')
    added[0].update(simulationOnly=True, diagnosticOnly=True)
    for target in added[0]['targets'].values():
        target.update(simulationOnly=True, diagnosticOnly=True)
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
        contract.require(not target.exists() or str(relative) in builder.RUNTIME_WEB_FILES, 'Existing immutable resource overwrite refused: ' + str(relative))
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
    from scripts import build_full_video_app_release as builder
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
    for name in builder.RUNTIME_WEB_FILES:
        src, target = builder.RUNTIME_WEB_ROOT / name, out / 'public' / name
        if not target.exists() or digest(src) != digest(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            changed.append('/' + name)
    contract.require(digest(out / 'public/multilingual-v3.json') == digest(base / 'public/multilingual-v3.json'), 'Runtime repair changed catalog')
    write(out / 'seal-report.json', {**catalog_report(out / 'public'), 'files': files_report(out / 'public')})
    contract.validate_catalog_snapshot(out)
    write(out / 'publish-config.json', publication_config(base, out))
    write(out / 'runtime-repair-plan.json', {'status': 'prepared_not_deployed', 'runtimeFiles': list(builder.RUNTIME_WEB_FILES), 'changedPaths': changed,
          'catalogUnchanged': True, 'modelCalls': 0, 'productionEligible': False})
    return {'status': 'prepared_not_deployed', 'changedPaths': changed, 'publishConfig': str(out / 'publish-config.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    b = commands.add_parser('baseline')
    b.add_argument('--out', required=True, type=Path)
    b.add_argument('--cache-public', type=Path)
    b.add_argument('--cache-receipt', type=Path)
    a = commands.add_parser('asset-first')
    a.add_argument('--baseline', required=True, type=Path)
    a.add_argument('--prepared', required=True, type=Path)
    a.add_argument('--out', required=True, type=Path)
    a.add_argument('--source-video', type=Path)
    o = commands.add_parser('overlay')
    o.add_argument('--baseline', required=True, type=Path)
    o.add_argument('--overlay-public', required=True, type=Path)
    o.add_argument('--catalog', required=True, type=Path)
    o.add_argument('--out', required=True, type=Path)
    plan = commands.add_parser('release-plan')
    plan.add_argument('--baseline', required=True, type=Path)
    plan.add_argument('--prepared', required=True, type=Path)
    plan.add_argument('--out', required=True, type=Path)
    repair = commands.add_parser('runtime-repair')
    repair.add_argument('--baseline', required=True, type=Path)
    repair.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.action == 'baseline':
        result = baseline(args.out, cache_public=args.cache_public, cache_receipt=args.cache_receipt)
    elif args.action == 'asset-first':
        result = asset_first(args.baseline, args.prepared, args.out, args.source_video)
    elif args.action == 'release-plan':
        result = release_plan(args.baseline, args.prepared, args.out)
    elif args.action == 'runtime-repair':
        result = runtime_repair(args.baseline, args.out)
    else:
        result = overlay(args.baseline, args.overlay_public, args.catalog, args.out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
