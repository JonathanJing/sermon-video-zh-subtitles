"""Validate native stage evidence; unsupported Production approvals stay closed.

V3 does not accept generic status/hash wrappers as producer receipts. There is
currently no versioned Production authorization or rollback capture producer,
so even valid supported stages cannot authorize Firebase deployment.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime
from pathlib import Path

SCHEMA = 'sermon-production-content-release-admission-v3'
REQUIRED = {
    'weeklyProduction': ('complete', 'packageSha256'),
    'devHttp': ('published_http_verified', 'httpReceiptSha256'),
    'rollbackBaseline': ('captured', 'baselineSha256'),
    'productionAuthorization': ('approved', 'approvalSha256'),
    'preDeployVerification': ('pass', 'candidateSha256'),
}
UNSUPPORTED = ('rollbackBaseline', 'productionAuthorization')


def _sha256(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _require(value):
    if not value:
        raise ValueError('invalid_stage_receipt')


def _blocked(missing, page_id=None, verified=None):
    return {'schemaVersion': SCHEMA, 'decision': 'blocked', 'contentDeploy': False,
            'pageId': page_id, 'missing': missing, 'verifiedStages': verified or [],
            'unsupportedStageContracts': list(UNSUPPORTED),
            'codePromotionAuthorizesContent': False, 'deviceOrVenueAuthorizesContent': False}


def _path(value, root):
    _require(type(value) is str and bool(value))
    path = Path(value)
    if not path.is_absolute():
        _require(root is not None)
        path = Path(root) / path
    return path


def _page(public, page_id):
    from scripts import assemble_multilingual_hosting as hosting
    catalog = hosting.load(public / hosting.CATALOG)
    hosting.validate_catalog(catalog)
    hosting.verify_catalog_assets(public, catalog)
    pages = [p for p in catalog['pages'] if p['id'] == page_id]
    _require(len(pages) == 1)
    return pages[0]


def _weekly(receipt, path, report, candidate):
    from scripts import assemble_multilingual_hosting as hosting
    _require(receipt.get('schemaVersion') == 'sermon-formal-dev-stage-receipt-v1'
             and receipt.get('deploymentStatus') == 'not_deployed'
             and receipt.get('httpVerification') == 'not_run'
             and receipt.get('deviceAcceptance') == 'not_run'
             and hosting.digest(path) == report.get('stagingReceiptSha256')
             and receipt.get('catalogPath') == '/multilingual-v2.json'
             and hosting.digest(path.parent / hosting.CATALOG) == receipt.get('catalogSha256'))
    catalog = hosting.load(path.parent / hosting.CATALOG)
    _require(len(catalog['pages']) == 1)
    staged = _page(path.parent, report['newPageId'])
    current = _page(candidate / 'public', report['newPageId'])
    refs = hosting.verify_catalog_assets(path.parent, catalog)
    _require(staged == current and receipt.get('sourceIdentitySha256') == current['sourceIdentitySha256']
             and set(receipt.get('targetLocales', [])) == set(current['targets'])
             and receipt.get('releasePackageSha256') == {
                 locale: target['releasePackageJsonSha256'] for locale, target in current['targets'].items()}
             and receipt.get('assetCount') == len(refs)
             and set(hosting.regular_files(path.parent)) == refs | {hosting.CATALOG, path.name})


def _dev_http(receipt, value, root, report, candidate):
    from scripts import multilingual_dev_preview as preview
    from scripts import assemble_multilingual_hosting as hosting
    dev = _path(value.get('candidatePath'), root)
    dev_report = preview.candidate_report(dev)
    _require(receipt.get('schemaVersion') == 'sermon-multilingual-dev-preview-http-v1'
             and receipt.get('status') == 'pass' and receipt.get('origin') == preview.DEV_ORIGIN
             and receipt.get('buildReportSha256') == hosting.digest(dev / 'build-report.json')
             and receipt.get('pageId') == dev_report['pageId'] == report['newPageId']
             and receipt.get('checkedFiles') == len(dev_report['files']))
    _require(datetime.fromisoformat(receipt['verifiedAt']).utcoffset() is not None)
    for field in ('browserAcceptance', 'deviceAcceptance', 'venueAcceptance'):
        _require(receipt.get(field) == 'not_run')
    page = _page(dev / 'public', report['newPageId'])
    _require(page == _page(candidate / 'public', report['newPageId']))
    results = receipt['results']
    _require(type(results) is list and all(type(row) is dict for row in results))
    for item in dev_report['files']:
        matched = [r for r in results if r.get('path') == '/' + item['path'] and 'sha256' in r]
        _require(len(matched) == 1 and matched[0].get('sha256') == item['sha256']
                 and matched[0].get('bytes') == item['bytes'] and bool(matched[0].get('contentType')))
    for locale, target in page['targets'].items():
        release = hosting.load(dev / 'public' / target['releasePackageUrl'].lstrip('/'))
        audio = next(a for a in release['assets'] if a['role'] == 'audio')
        _require(any(r.get('path') == audio['path'] and r.get('range206') is True for r in results)
                 and any(r.get('path') == f'/pages/{page["id"]}/{locale}' and r.get('status') == 200 for r in results))


def admit(evidence, *, candidate_sha256=None, preflight_sha256=None, evidence_dir=None, candidate_dir=None):
    if type(evidence) is not dict:
        raise ValueError('content_release_evidence_invalid')
    if not _sha256(candidate_sha256) or not _sha256(preflight_sha256) or candidate_dir is None:
        return _blocked(['current_candidate_binding'])
    from scripts import assemble_multilingual_hosting as hosting
    candidate = Path(candidate_dir)
    try:
        report = hosting.load(candidate / 'build-report.json')
        _require(hosting.digest(candidate / 'build-report.json') == candidate_sha256
                 and report.get('schemaVersion') == 'sermon-multilingual-hosting-candidate-v1'
                 and report.get('status') == 'validated_not_deployed' and report.get('productionReader') is True)
        page_id = report['newPageId']
    except (OSError, ValueError, KeyError, TypeError):
        return _blocked(['current_candidate_binding'])
    missing, verified = [], []
    for key, (status, digest_key) in REQUIRED.items():
        if key in UNSUPPORTED:
            missing.append(key)
            continue
        try:
            value = evidence[key]
            _require(type(value) is dict and value.get('status') == status and value.get('pageId') == page_id)
            path = _path(value.get('receiptPath'), evidence_dir)
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            _require(digest == value.get('receiptSha256') and _sha256(digest))
            receipt = json.loads(raw)
            _require(type(receipt) is dict and receipt.get('pageId') == page_id)
            if key == 'preDeployVerification':
                _require(value.get(digest_key) == candidate_sha256 and digest == preflight_sha256)
                from scripts import deploy_multilingual_hosting as deploy
                deploy.prepare(candidate, path)
                _require(type(receipt.get('results')) is list and
                         all(type(row) is dict for row in receipt['results']))
                _require(sorted(receipt['results'], key=lambda row: row['path']) ==
                         sorted([{'path': '/' + item['path'], 'sha256': item['sha256'],
                                  'bytes': item['bytes']} for item in report['baseFiles']],
                                key=lambda row: row['path']))
            else:
                _require(value.get(digest_key) == digest)
                if key == 'weeklyProduction':
                    _weekly(receipt, path, report, candidate)
                else:
                    _dev_http(receipt, value, evidence_dir, report, candidate)
            verified.append(key)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, StopIteration):
            missing.append(key)
    return _blocked(missing, page_id, verified)


def load(path, *, candidate_sha256=None, preflight_sha256=None, candidate_dir=None):
    try:
        evidence = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('content_release_evidence_invalid') from exc
    return admit(evidence, candidate_sha256=candidate_sha256, preflight_sha256=preflight_sha256,
                 evidence_dir=Path(path).parent, candidate_dir=candidate_dir)
