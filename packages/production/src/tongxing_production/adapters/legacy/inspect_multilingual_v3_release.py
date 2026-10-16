#!/usr/bin/env python3
"""Inspect an assembled v3 candidate against a local baseline, without network.

This proves local snapshot consistency only. It neither validates independent
human approval receipts nor proves that the baseline is current on the server.
No deployment adapter consumes this receipt as authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import assemble_multilingual_v3_update as producer
from scripts import deploy_multilingual_hosting as target
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-v3-local-release-inspection-v1'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _code_snapshot():
    def git(*args):
        return subprocess.check_output(['git', '-C', str(producer.ROOT), *args], text=True).strip()
    return {'commit': git('rev-parse', 'HEAD'),
            'workingTreeClean': not git('status', '--porcelain', '--untracked-files=normal')}


def _snapshot(root):
    root = _safe_path(Path(root).absolute())
    return {name: {'sha256': producer.digest(path), 'bytes': path.stat().st_size}
            for name, path in sorted(producer.regular_files(root).items())}


def _catalog(path):
    value = producer.load(path)
    producer.validate_schema(value, producer.SCHEMA)
    ids = [p['id'] for p in value['pages']]
    require(len(ids) == len(set(ids)) and value['defaultPageId'] in ids,
            'invalid_catalog_page_set')
    return value


def inspect(candidate, baseline, *, expected_commit, expected_report_sha256,
            project, site, video_file=None):
    require((project, site) == (target.PROJECT, target.SITE), 'unexpected_production_target')
    require(isinstance(expected_commit, str) and re.fullmatch('[a-f0-9]{40}', expected_commit),
            'invalid_expected_code_commit')
    require(_sha(expected_report_sha256), 'invalid_expected_build_report_sha256')
    code = _code_snapshot()
    require(code == {'commit': expected_commit, 'workingTreeClean': True}, 'code_checkout_changed_or_dirty')
    candidate, baseline = (_safe_path(Path(p).absolute()) for p in (candidate, baseline))
    public = candidate / 'public'
    before, base = _snapshot(candidate), _snapshot(baseline)
    report_path = candidate / 'build-report.json'
    require(before.get('build-report.json', {}).get('sha256') == expected_report_sha256,
            'selected_build_report_changed')
    report = producer.load(report_path)
    require(report.get('schemaVersion') == 'sermon-multilingual-v3-update-candidate-v2'
            and report.get('status') == 'validated_not_deployed', 'unsupported_candidate')
    profile = report.get('publicationProfile')
    require(profile in {producer.PUBLICATION_PROFILE, producer.BUCKET_PROFILE}, 'unsupported_publication_profile')
    bucket = profile == producer.BUCKET_PROFILE
    allowed = {'build-report.json', 'rollback-' + producer.CATALOG}
    if bucket:
        allowed.add('firebase.json')
    require({name for name in before if not name.startswith('public/')} == allowed,
            'unlisted_candidate_metadata')
    files = report.get('files')
    require(isinstance(files, list) and files, 'invalid_candidate_manifest')
    admitted = {}
    for row in files:
        require(isinstance(row, dict) and set(row) == {'path', 'bytes', 'sha256'}, 'invalid_manifest_entry')
        name = row['path']
        require(isinstance(name, str) and name and not name.startswith('/')
                and '\\' not in name and all(p not in {'', '.', '..'} for p in name.split('/'))
                and not any(ord(c) < 32 for c in name) and name not in admitted
                and type(row['bytes']) is int and row['bytes'] >= 0 and _sha(row['sha256']),
                'unsafe_or_duplicate_manifest_entry')
        admitted[name] = {'bytes': row['bytes'], 'sha256': row['sha256']}
    actual = {name[7:]: identity for name, identity in before.items() if name.startswith('public/')}
    require(actual == admitted, 'candidate_manifest_mismatch')
    require(producer.CATALOG in base and 'weekly.json' in base, 'incomplete_local_baseline')
    require(base[producer.CATALOG]['sha256'] == report.get('oldCatalogSha256')
            and before['rollback-' + producer.CATALOG] == base[producer.CATALOG], 'baseline_or_rollback_changed')
    require(actual.get(producer.CATALOG, {}).get('sha256') == report.get('newCatalogSha256'), 'new_catalog_changed')
    old, new = _catalog(baseline / producer.CATALOG), _catalog(public / producer.CATALOG)
    old_pages, pages = ({p['id']: p for p in value['pages']} for value in (old, new))
    page_id = report.get('pageId')
    require(isinstance(page_id, str) and set(pages) - set(old_pages) == {page_id}
            and set(old_pages) <= set(pages) and new['defaultPageId'] == page_id,
            'unexpected_page_change')
    require(all(pages[name] == page for name, page in old_pages.items()), 'historical_page_changed')
    require(all(name in actual and actual[name] == identity for name, identity in base.items()
                if name != producer.CATALOG), 'baseline_asset_changed_or_removed')
    page = pages[page_id]
    require(set(page['targets']) == producer.SUPPORTED_LOCALES
            and report.get('targetLocales') == sorted(producer.SUPPORTED_LOCALES)
            and all(t['audioStatus'] == 'human_reviewed' and 'alignment' in t['capabilities']
                    and t.get('audioFingerprint') for t in page['targets'].values()), 'weekly_profile_changed')
    for prior in old['pages']:
        producer.validate_page(baseline, prior)
        producer.validate_page(public, prior)
    added = set(actual) - set(base)
    require(producer.validate_page(public, page) == added, 'weekly_asset_set_changed')
    count = producer.BUCKET_STAGE_FILE_COUNT if bucket else producer.STAGE_FILE_COUNT
    expected_counts = {'baseFileCount': len(base), 'addedFileCount': count,
                       'catalogUpdateFileCount': 1, 'weeklyFileCount': count + 1,
                       'bucketObjectCount': int(bucket), 'weeklyFirebaseObjectCount': count + 1 + int(bucket)}
    require(len(added) == count and all(type(report.get(k)) is int and report[k] == v
                                       for k, v in expected_counts.items()), 'candidate_counts_changed')
    delivery = page.get('videoDelivery')
    require(report.get('videoDelivery') == delivery and bool(delivery) == bucket, 'video_delivery_changed')
    video_identity = None
    if bucket:
        require('/ai-for-god-sermon-media-prod/' in delivery['storageUrl'], 'unexpected_video_bucket')
        require(report.get('firebaseConfigSha256') == before['firebase.json']['sha256'], 'hosting_config_changed')
        config = producer.load(candidate / 'firebase.json')
        hosting = config.get('hosting')
        require(isinstance(hosting, dict) and hosting.get('public') == 'public'
                and hosting.get('site') in (None, target.SITE)
                and hosting.get('target') in (None, 'sermonDubbing')
                and (hosting.get('site') == target.SITE or hosting.get('target') == 'sermonDubbing'),
                'unexpected_candidate_hosting_target')
        for item in new['pages']:
            if item.get('videoDelivery'):
                producer.require_video_redirect(config, item['videoDelivery'])
        require(video_file is not None, 'local_bucket_video_required')
        video_file = _safe_path(Path(video_file).absolute())
        require(video_file.is_file() and video_file.stat().st_size == delivery['bytes']
                and producer.digest(video_file) == delivery['sha256'], 'local_bucket_video_changed')
        video_identity = {'sha256': delivery['sha256'], 'bytes': delivery['bytes']}
    else:
        require(video_file is None and report.get('firebaseConfigSha256') is None, 'unexpected_video_or_hosting_config')
    releases = {}
    for locale, row in page['targets'].items():
        release = producer.load(public / row['releasePackageUrl'].lstrip('/'))
        releases[locale] = {key: release[key] for key in ('targetLanguageCandidateJsonSha256',
            'spokenTargetLanguageCandidateJsonSha256', 'targetLanguageAudioPackageJsonSha256')}
        releases[locale]['releaseFileSha256'] = row['releasePackageJsonSha256']
    # Reject evidence mutated during semantic validation, rather than certify a
    # mixture of snapshots. A later deploy must bind and recheck all identities.
    require(_snapshot(candidate) == before and _snapshot(baseline) == base
            and _code_snapshot() == code, 'inspection_inputs_changed')
    if video_file is not None:
        require(video_file.stat().st_size == video_identity['bytes']
                and producer.digest(video_file) == video_identity['sha256'], 'inspection_video_changed')
    return {'schemaVersion': SCHEMA, 'status': 'local_snapshot_consistent_release_gates_pending',
            'deploymentAllowed': False, 'networkAccessed': False,
            'target': {'environment': 'production', 'projectId': project, 'siteId': site},
            'codeCommit': expected_commit, 'pageId': page_id, 'targetLocales': sorted(releases),
            'buildReportSha256': expected_report_sha256, 'candidateSnapshotSha256': _digest(before),
            'baselineSnapshotSha256': _digest(base), 'rollbackCatalogSha256': report['oldCatalogSha256'],
            'upstreamPackageBindings': releases, 'bucketVideo': video_identity,
            'files': {'add': sorted(added), 'replace': [producer.CATALOG],
                      'preserve': sorted(set(base) - {producer.CATALOG})},
            'requiredIndependentGates': ['current_online_baseline', 'upstream_human_approval_receipts',
                'exact_release_authorization', 'protected_code_promotion', 'firebase_target_mapping', 'site_serialization',
                'post_deploy_http_and_range', 'web_device_venue_acceptance_separately'],
            'humanAcceptance': 'not_evaluated', 'deviceAcceptance': 'not_run', 'venueAcceptance': 'not_run'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'baseline'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('expected-commit', 'expected-report-sha256', 'project', 'site'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--video-file', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.candidate, args.baseline, expected_commit=args.expected_commit,
        expected_report_sha256=args.expected_report_sha256, project=args.project, site=args.site,
        video_file=args.video_file), sort_keys=True))


if __name__ == '__main__':
    main()
