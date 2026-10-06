"""Resume the zero-model-API Dev diagnostic delivery chain from prepared assets.

Without --execute this validates local inputs and prints the exact Dev target.
Execution publishes assets first, verifies HTTP bytes, seals against the actual
live baseline, then publishes the isolated catalog overlay and reads it back.
Formal approval, model production, Beta builds and playback are not inferred.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import build_full_video_app_release as builder
from scripts import delivery_contract as contract
from scripts import guarded_hosting_publish as publisher
from scripts import prepare_dev_simulated_publication as preparation
from scripts.sermon_execution_harness import atomic_json


def now():
    return datetime.now(timezone.utc).isoformat()


def monitor_metrics(path=None):
    """Use externally observed output usage/time only; never guess from CLI waits."""
    if path is None:
        return {'status': 'not_instrumented', 'outputTokens': None,
                'generationSeconds': None, 'tokensPerSecond': None}
    data = preparation.read(path)
    contract.require(data.get('schemaVersion') == 'sermon-codex-monitor-metrics-v1',
                     'Unsupported monitor metrics schema')
    turns = data.get('turns')
    contract.require(isinstance(turns, list) and turns, 'Observed turns required')
    ids = set()
    tokens, seconds = 0, 0.0
    for turn in turns:
        turn_id = turn.get('turnId')
        count, elapsed = turn.get('outputTokens'), turn.get('generationSeconds')
        contract.require(isinstance(turn_id, str) and turn_id and turn_id not in ids,
                         'Unique monitor turn IDs required')
        contract.require(type(count) is int and count >= 0 and type(elapsed) in (int, float)
                         and 0 < elapsed < float('inf') and turn.get('evidenceRef'),
                         'Observed output tokens, generation duration and evidence required')
        ids.add(turn_id)
        tokens += count
        seconds += elapsed
    return {'status': 'externally_observed', 'outputTokens': tokens,
            'generationSeconds': seconds, 'tokensPerSecond': tokens / seconds,
            'sourceSha256': preparation.digest(path), 'includesToolWaits': False}


class Journal:
    """Input-bound stage receipts; resume only unchanged, validated outputs."""
    def __init__(self, root, identity):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'workflow-state.json'
        self.identity = contract.sha(identity)
        if self.path.exists():
            self.data = preparation.read(self.path)
            contract.require(self.data['inputIdentitySha256'] == self.identity,
                             'Workflow inputs changed; use a new run directory')
        else:
            self.data = {'schemaVersion': 'sermon-dev-diagnostic-workflow-v1',
                         'inputIdentitySha256': self.identity, 'inputs': identity,
                         'startedAt': now(), 'stages': {}, 'attempts': [], 'status': 'running'}
            atomic_json(self.path, self.data)

    def stage(self, name, action, outputs, validate=lambda: None, *, always=False):
        previous = self.data['stages'].get(name)
        if previous and previous['status'] == 'succeeded' and not always:
            try:
                contract.require(previous['outputs'] == self.hashes(outputs),
                                 'Completed stage output changed: ' + name)
                validate()
            except BaseException as exc:
                self.data.update(status='needs_attention', currentStage=name)
                previous.update(status='needs_attention', errorType=type(exc).__name__)
                atomic_json(self.path, self.data)
                raise
            return
        self.data['status'] = 'running'
        self.data['currentStage'] = name
        self.data['stages'][name] = {'status': 'running', 'startedAt': now()}
        atomic_json(self.path, self.data)
        started = time.monotonic()
        try:
            action()
            validate()
            self.data['stages'][name].update(status='succeeded', completedAt=now(),
                executionSeconds=time.monotonic() - started, outputs=self.hashes(outputs))
        except BaseException as exc:
            # Exception text can contain URLs/credentials; retain only its type.
            self.data['status'] = 'needs_attention'
            self.data['stages'][name].update(status='needs_attention', completedAt=now(),
                executionSeconds=time.monotonic() - started, errorType=type(exc).__name__)
            raise
        finally:
            self.data['attempts'].append({'stage': name, **{k: v for k, v in
                self.data['stages'][name].items() if k != 'outputs'}})
            atomic_json(self.path, self.data)

    def hashes(self, paths):
        return {str(Path(p).relative_to(self.root)): preparation.digest(p) for p in paths}


def reader(url):
    with urlopen(Request(url, headers={'Cache-Control': 'no-cache'}), timeout=120) as response:
        return response.status, response.read()


def publish_once(snapshot):
    receipt_path = snapshot / 'deployment-attempt-v2.json'
    if receipt_path.exists():
        receipt = preparation.read(receipt_path)
        contract.require(receipt['status'] == 'deployed',
                         'Existing deployment requires explicit reconciliation; no automatic retry')
        contract.require(receipt['intent']['site'] == preparation.SITE, 'Wrong deployed site')
        contract.require(receipt['catalogSha256'] == preparation.digest(snapshot / 'public/multilingual-v3.json'),
                         'Deployed snapshot changed')
        return receipt
    return publisher.publish(**preparation.read(snapshot / 'publish-config.json'),
                             request=publisher.authenticated_transport(), reader=reader)


def live_readback(snapshot, page_id, out):
    catalog_file = snapshot / 'public/multilingual-v3.json'
    status, data = reader(preparation.ORIGIN + '/multilingual-v3.json')
    contract.require(status == 200 and hashlib.sha256(data).hexdigest() == preparation.digest(catalog_file),
                     'Live catalog differs from deployed snapshot')
    catalog = json.loads(data)
    page = next(p for p in catalog['pages'] if p['id'] == page_id)
    expected_files = {row['path']: row for row in preparation.read(snapshot / 'seal-report.json')['files']}
    contract.require(page.get('simulationOnly') and page.get('diagnosticOnly'), 'Missing test isolation')
    def check_asset(asset):
        # Stream audio/media; do not retain large remote binaries in memory.
        with urlopen(Request(preparation.ORIGIN + asset['path'], headers={'Cache-Control': 'no-cache'}), timeout=120) as response:
            digest, size = hashlib.sha256(), 0
            contract.require(response.status == 200, 'Live asset GET failed')
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        contract.require(digest.hexdigest() == asset['sha256'] and size == expected_files[asset['path']]['bytes'],
                         'Live asset hash/size differs')
        return {'path': asset['path'], 'status': 'pass', 'sha256': digest.hexdigest(), 'bytes': size}

    observations = {}
    for locale, target in page['targets'].items():
        contract.require(target.get('simulationOnly') and target.get('diagnosticOnly'), 'Missing locale isolation')
        status, raw = reader(preparation.ORIGIN + target['releasePackageUrl'])
        contract.require(status == 200 and hashlib.sha256(raw).hexdigest() == target['releasePackageJsonSha256'],
                         'Live release hash differs')
        release = json.loads(raw)
        contract.validate_release_schema(release)
        contract.require(release['status'] == 'published_http_verified', 'Release not HTTP verified')
        checked = []
        for asset in release['assets']:
            checked.append(check_asset(asset))
        observations[locale] = checked
    source_video = check_asset(expected_files['/media/' + page_id + '/source.mp4'])
    preparation.write(out, {'schemaVersion': 'sermon-dev-diagnostic-live-readback-v1',
        'status': 'pass', 'checkedAt': now(), 'pageId': page_id, 'locales': observations,
        'sourceVideo': source_video,
        'playback': 'not_run', 'physicalDevice': 'not_run', 'venueAcceptance': 'not_run'})


def _run(args):
    base, prepared, root = (p.resolve() for p in (args.baseline, args.prepared, args.out))
    manifest, assets = builder.verified_assets(prepared)
    baseline_catalog = contract.validate_catalog_snapshot(base)
    page_id = manifest['pageId']
    contract.require(page_id.startswith(('mockup-', 'dryrun-', 'dev-')), 'Diagnostic page ID required')
    contract.require(set(manifest['releases']) == {'zh-Hans', 'ko', 'es'}, 'Three locales required')
    contract.require(all(page['id'] != page_id for page in baseline_catalog['pages']),
                     'Test page already exists; build a new run-specific page ID')
    contents = [preparation.read(prepared / 'public' / preparation.safe_relative(row['path']))
                for row in assets if row['role'] == 'content']
    contract.require(len(contents) == 3 and all(c.get('reviewMode') == 'simulation' for c in contents),
                     'Explicit simulated content required')
    for content in contents:
        relative = preparation.safe_relative(content['sourceVideoUrl'])
        contract.require(str(relative) == 'media/' + page_id + '/source.mp4', 'Source video page binding differs')
        source = args.source_video if args.source_video else base / 'public' / relative
        contract.require(source.is_file() and preparation.digest(source) == content['sourceMediaSha256'],
                         'Bound cached source video required')
    contract.require(not root.is_relative_to(base) and not root.is_relative_to(prepared)
                     and not base.is_relative_to(root) and not prepared.is_relative_to(root), 'Unsafe workflow output')
    base_receipt = preparation.read(base / 'baseline-receipt.json')
    contract.require(base_receipt['site'] == preparation.SITE and base_receipt['project'] == preparation.PROJECT
                     and base_receipt['origin'] == preparation.ORIGIN, 'Dev target only')
    identity = {'pageId': page_id, 'preparedManifestSha256': preparation.digest(prepared / 'preparation-manifest.json'),
                'preparedAssetsSha256': contract.sha(assets), 'baselineReceiptSha256': preparation.digest(base / 'baseline-receipt.json'),
                'baselineSealSha256': preparation.digest(base / 'seal-report.json'),
                'sourceVideoSha256': preparation.digest(args.source_video) if args.source_video else None,
                'implementationSha256s': {Path(module.__file__).name: preparation.digest(module.__file__)
                    for module in (builder, preparation, publisher, contract)},
                'executorSha256': preparation.digest(Path(__file__)),
                'target': {'site': preparation.SITE, 'origin': preparation.ORIGIN}}
    plan = {'status': 'validated_not_deployed', 'inputs': identity, 'modelApiRequests': 0,
            'deploymentChannel': 'dev', 'betaBuild': 'not_run', 'playback': 'not_run'}
    metrics = monitor_metrics(args.monitor_metrics)
    if not args.execute:
        return {**plan, 'monitorMetrics': metrics}
    journal = Journal(root, identity)
    first, live, sealed, final = (root / p for p in ('asset-first', 'live-baseline', 'sealed', 'final-overlay'))
    verification, release_plan = root / 'assets-http-verification.json', root / 'release-plan.json'
    journal.stage('prepare_assets', lambda: preparation.asset_first(base, prepared, first, args.source_video),
                  [first / 'seal-report.json', first / 'publish-config.json'], lambda: contract.validate_catalog_snapshot(first))
    journal.stage('publish_assets', lambda: publish_once(first), [first / 'deployment-attempt-v2.json'])
    journal.stage('refresh_baseline', lambda: preparation.baseline(live, cache_public=base / 'public', cache_receipt=base / 'baseline-receipt.json'),
                  [live / 'seal-report.json', live / 'baseline-receipt.json'], lambda: contract.validate_catalog_snapshot(live))
    contract.require(preparation.read(live / 'baseline-receipt.json')['baselineVersion'] == preparation.read(first / 'deployment-attempt-v2.json')['newVersion'],
                     'Live version changed after asset deployment; start a new bound run')
    journal.stage('verify_assets', lambda: builder.verify(argparse.Namespace(prepared=prepared, origin=preparation.ORIGIN, out=verification)), [verification])
    journal.stage('release_plan', lambda: preparation.release_plan(live, prepared, release_plan), [release_plan])
    journal.stage('seal', lambda: builder.seal(argparse.Namespace(prepared=prepared, baseline=live, release_plan=release_plan,
                  http_verification=verification, out=sealed)), [sealed / 'seal-report.json'], lambda: contract.validate_catalog_snapshot(sealed))
    journal.stage('prepare_overlay', lambda: preparation.overlay(live, sealed / 'public', sealed / 'public/multilingual-v3.json', final),
                  [final / 'seal-report.json', final / 'publish-config.json'], lambda: contract.validate_catalog_snapshot(final))
    journal.stage('publish_catalog', lambda: publish_once(final), [final / 'deployment-attempt-v2.json'])
    # Always rerun external verification on resume: cached HTTP evidence is historical.
    readback = root / ('live-readback-' + str(time.time_ns()) + '.json')
    journal.stage('live_readback', lambda: live_readback(final, page_id, readback), [readback], always=True)
    result = {**plan, 'status': 'diagnostic_dev_http_verified', 'monitorMetrics': metrics,
              'modelApiTokens': 0, 'modelApiCostUsd': 0, 'formalContentApproval': False,
              'readback': str(readback), 'deploymentReceipt': str(final / 'deployment-attempt-v2.json'),
              'workflowWallClockSeconds': (datetime.now(timezone.utc) - datetime.fromisoformat(journal.data['startedAt'])).total_seconds(),
              'stageExecutionSeconds': {name: sum(attempt['executionSeconds'] for attempt in journal.data['attempts']
                   if attempt['stage'] == name) for name in journal.data['stages']},
              'stageTimingIncludesToolWaits': True}
    journal.data.update(status=result['status'], completedAt=now())
    atomic_json(journal.path, journal.data)
    atomic_json(root / 'run-report.json', result)
    return result


def run(args):
    if not args.execute:
        return _run(args)
    root = args.out.resolve()
    # Refuse nesting before creating any lock/output inside input artifacts.
    for source in (args.baseline.resolve(), args.prepared.resolve()):
        contract.require(not root.is_relative_to(source) and not source.is_relative_to(root), 'Unsafe workflow output')
    root.mkdir(parents=True, exist_ok=True)
    with publisher.publisher_lock(root):
        return _run(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'prepared', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-video', type=Path)
    parser.add_argument('--monitor-metrics', type=Path, help='Observed Codex output usage and generation time; omit to report TPS as null')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False))


if __name__ == '__main__':
    main()
