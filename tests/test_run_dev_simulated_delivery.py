import json
import argparse
import io
from pathlib import Path

import pytest

from scripts import run_dev_simulated_delivery as runner


def test_resume_preserves_successful_stages_and_refuses_tampered_outputs(tmp_path):
    journal = runner.Journal(tmp_path, {'source': 'frozen'})
    output = tmp_path / 'receipt.json'
    calls = []

    def produce():
        calls.append('publish')
        output.write_text('{"status":"deployed"}')

    journal.stage('publish', produce, [output])
    resumed = runner.Journal(tmp_path, {'source': 'frozen'})
    resumed.stage('publish', produce, [output])
    assert calls == ['publish']
    output.write_text('{"status":"unknown"}')
    with pytest.raises(ValueError, match='output changed'):
        resumed.stage('publish', produce, [output])
    assert calls == ['publish']
    with pytest.raises(ValueError, match='inputs changed'):
        runner.Journal(tmp_path, {'source': 'revised'})


def test_stage_failure_preserves_completed_work_and_safe_error_only(tmp_path):
    journal = runner.Journal(tmp_path, {})
    output = tmp_path / 'prepared.json'
    journal.stage('prepare', lambda: output.write_text('{}'), [output])

    def uncertain():
        raise TimeoutError('credential must never reach state')

    with pytest.raises(TimeoutError):
        journal.stage('publish', uncertain, [])
    state = json.loads(journal.path.read_text())
    assert state['status'] == 'needs_attention'
    assert state['stages']['prepare']['status'] == 'succeeded'
    assert state['stages']['publish']['errorType'] == 'TimeoutError'
    assert 'credential' not in journal.path.read_text()


def test_external_readback_reruns_on_resume(tmp_path):
    journal = runner.Journal(tmp_path, {})
    calls = []
    for filename in ('readback1.json', 'readback2.json'):
        path = tmp_path / filename
        journal.stage('readback', lambda: (calls.append(filename), path.write_text('{}')),
                      [path], always=True)
    assert len(calls) == 2


def test_unknown_deployment_never_retries_or_acquires_new_credentials(tmp_path, monkeypatch):
    (tmp_path / 'deployment-attempt-v2.json').write_text('{"status":"outcome_unknown"}')
    monkeypatch.setattr(runner.publisher, 'authenticated_transport', lambda: pytest.fail('No new transport allowed'))
    with pytest.raises(ValueError, match='explicit reconciliation'):
        runner.publish_once(tmp_path)


def test_confirmed_receipt_recovered_after_journal_write_interruption(tmp_path, monkeypatch):
    public = tmp_path / 'public'
    public.mkdir()
    catalog = public / 'multilingual-v3.json'
    catalog.write_text('{}')
    receipt = {'status': 'deployed', 'intent': {'site': runner.preparation.SITE},
               'catalogSha256': runner.preparation.digest(catalog)}
    (tmp_path / 'deployment-attempt-v2.json').write_text(json.dumps(receipt))
    monkeypatch.setattr(runner.publisher, 'authenticated_transport', lambda: pytest.fail('No second deploy'))
    assert runner.publish_once(tmp_path) == receipt
    catalog.write_text('{"changed":true}')
    with pytest.raises(ValueError, match='snapshot changed'):
        runner.publish_once(tmp_path)


def test_monitor_metrics_use_output_tokens_and_generation_time_only(tmp_path):
    assert runner.monitor_metrics()['tokensPerSecond'] is None
    path = tmp_path / 'observed.json'
    data = {'schemaVersion': 'sermon-codex-monitor-metrics-v1', 'turns': [
        {'turnId': '1', 'outputTokens': 100, 'inputTokens': 9000,
         'generationSeconds': 2, 'toolWaitSeconds': 80, 'evidenceRef': 'observed-turn-1'},
        {'turnId': '2', 'outputTokens': 200, 'generationSeconds': 4, 'evidenceRef': 'observed-turn-2'}]}
    path.write_text(json.dumps(data))
    metrics = runner.monitor_metrics(path)
    assert metrics['tokensPerSecond'] == 50
    assert metrics['outputTokens'] == 300 and metrics['generationSeconds'] == 6
    data['turns'][1]['turnId'] = '1'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Unique'):
        runner.monitor_metrics(path)


@pytest.mark.parametrize('elapsed', [0, -1, True, float('nan'), float('inf')])
def test_invalid_generation_measurement_refused(tmp_path, elapsed):
    path = tmp_path / 'observed.json'
    path.write_text(json.dumps({'schemaVersion': 'sermon-codex-monitor-metrics-v1',
        'turns': [{'turnId': '1', 'outputTokens': 100, 'generationSeconds': elapsed, 'evidenceRef': 'receipt'}]}))
    with pytest.raises(ValueError, match='Observed'):
        runner.monitor_metrics(path)


def test_chain_resumes_http_failure_without_repeating_asset_publication(tmp_path, monkeypatch):
    base, prepared, root = (tmp_path / name for name in ('baseline', 'prepared', 'workflow'))
    base.mkdir(); prepared.mkdir()
    page = 'mockup-test-run'
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'frozen cached source')
    content = prepared / 'public/content.json'
    content.parent.mkdir()
    content.write_text(json.dumps({'reviewMode': 'simulation', 'sourceVideoUrl': '/media/' + page + '/source.mp4',
                                  'sourceMediaSha256': runner.preparation.digest(source)}))
    receipt = {'site': runner.preparation.SITE, 'project': runner.preparation.PROJECT,
               'origin': runner.preparation.ORIGIN, 'baselineVersion': 'old'}
    (base / 'baseline-receipt.json').write_text(json.dumps(receipt))
    (base / 'seal-report.json').write_text('{}')
    (prepared / 'preparation-manifest.json').write_text('{}')
    manifest = {'pageId': page, 'releases': {locale: {} for locale in ('zh-Hans', 'ko', 'es')}}
    assets = [{'role': 'content', 'path': '/content.json'}] * 3
    monkeypatch.setattr(runner.builder, 'verified_assets', lambda path: (manifest, assets))
    monkeypatch.setattr(runner.contract, 'validate_catalog_snapshot', lambda path: {'pages': []})
    events = []

    def snapshot(out):
        out.mkdir()
        (out / 'public').mkdir()
        (out / 'public/multilingual-v3.json').write_text('{}')
        (out / 'seal-report.json').write_text('{}')
        (out / 'publish-config.json').write_text(json.dumps({'snapshot': str(out)}))

    def prepare_assets(base, prepared, out, source):
        events.append('prepare_assets'); snapshot(out)

    def publish(**kwargs):
        directory = Path(kwargs['snapshot'])
        events.append('publish_' + directory.name)
        value = {'status': 'deployed', 'newVersion': 'new', 'intent': {'site': runner.preparation.SITE},
                 'catalogSha256': runner.preparation.digest(directory / 'public/multilingual-v3.json')}
        (directory / 'deployment-attempt-v2.json').write_text(json.dumps(value))
        return value

    def baseline(out, **kwargs):
        events.append('refresh_baseline'); snapshot(out)
        (out / 'baseline-receipt.json').write_text(json.dumps({**receipt, 'baselineVersion': 'new'}))

    def verify(args):
        events.append('verify')
        if events.count('verify') == 1:
            raise TimeoutError('temporary HTTP failure')
        args.out.write_text('{}')

    monkeypatch.setattr(runner.preparation, 'asset_first', prepare_assets)
    monkeypatch.setattr(runner.publisher, 'publish', publish)
    monkeypatch.setattr(runner.publisher, 'authenticated_transport', lambda: None)
    monkeypatch.setattr(runner.preparation, 'baseline', baseline)
    monkeypatch.setattr(runner.builder, 'verify', verify)
    monkeypatch.setattr(runner.preparation, 'release_plan', lambda base, prepared, out: out.write_text('{}'))
    monkeypatch.setattr(runner.builder, 'seal', lambda args: snapshot(args.out))
    monkeypatch.setattr(runner.preparation, 'overlay', lambda base, public, catalog, out: snapshot(out))
    monkeypatch.setattr(runner, 'live_readback', lambda final, page, out: (events.append('readback'), out.write_text('{}')))
    args = argparse.Namespace(baseline=base, prepared=prepared, out=root, source_video=source,
                              monitor_metrics=None, execute=True)
    with pytest.raises(TimeoutError):
        runner.run(args)
    result = runner.run(args)
    assert result['status'] == 'diagnostic_dev_http_verified'
    assert result['monitorMetrics']['tokensPerSecond'] is None
    assert events.count('publish_asset-first') == events.count('publish_final-overlay') == 1
    assert events.count('refresh_baseline') == 1
    assert events.index('publish_asset-first') < events.index('verify') < events.index('publish_final-overlay')
    runner.run(args)
    assert events.count('publish_asset-first') == events.count('publish_final-overlay') == 1
    assert events.count('readback') == 2


def test_live_readback_checks_source_video_and_refuses_changed_bytes(tmp_path, monkeypatch):
    public = tmp_path / 'public'
    public.mkdir()
    page = 'mockup-test'
    body = b'cached audio'
    source = b'cached video'
    audio_path, video_path = '/media/' + page + '/zh-Hans.mp3', '/media/' + page + '/source.mp4'
    release = {'status': 'published_http_verified', 'assets': [
        {'path': audio_path, 'sha256': runner.hashlib.sha256(body).hexdigest()}]}
    release_bytes = json.dumps(release).encode()
    catalog = {'pages': [{'id': page, 'simulationOnly': True, 'diagnosticOnly': True, 'targets': {
        'zh-Hans': {'simulationOnly': True, 'diagnosticOnly': True, 'releasePackageUrl': '/release.json',
                    'releasePackageJsonSha256': runner.hashlib.sha256(release_bytes).hexdigest()}}}]}
    raw = json.dumps(catalog).encode()
    (public / 'multilingual-v3.json').write_bytes(raw)
    (tmp_path / 'seal-report.json').write_text(json.dumps({'files': [
        {'path': audio_path, 'sha256': runner.hashlib.sha256(body).hexdigest(), 'bytes': len(body)},
        {'path': video_path, 'sha256': runner.hashlib.sha256(source).hexdigest(), 'bytes': len(source)}]}))
    monkeypatch.setattr(runner, 'reader', lambda url: (200, raw if url.endswith('multilingual-v3.json') else release_bytes))
    monkeypatch.setattr(runner.contract, 'validate_release_schema', lambda data: None)
    payloads = {runner.preparation.ORIGIN + audio_path: body, runner.preparation.ORIGIN + video_path: source}
    def open_response(request, **kwargs):
        response = io.BytesIO(payloads[request.full_url])
        response.status = 200
        return response
    monkeypatch.setattr(runner, 'urlopen', open_response)
    runner.live_readback(tmp_path, page, tmp_path / 'receipt.json')
    receipt = json.loads((tmp_path / 'receipt.json').read_text())
    assert receipt['sourceVideo']['sha256'] == runner.hashlib.sha256(source).hexdigest()
    assert receipt['playback'] == 'not_run'
    payloads[runner.preparation.ORIGIN + video_path] = b'altered'
    with pytest.raises(ValueError, match='hash/size differs'):
        runner.live_readback(tmp_path, page, tmp_path / 'bad.json')
    assert not (tmp_path / 'bad.json').exists()
