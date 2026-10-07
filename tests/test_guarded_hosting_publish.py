import hashlib
import json
from pathlib import Path
import pytest
import time
from scripts import guarded_hosting_publish as p


def setup(tmp_path):
    public = tmp_path / 'public'; public.mkdir()
    data = b'{"pages": []}'
    (public / 'multilingual-v3.json').write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    report = {'catalogSha256': sha, 'files': [{'path': '/multilingual-v3.json', 'sha256': sha, 'bytes': len(data)}]}
    (tmp_path / 'seal-report.json').write_text(json.dumps(report))
    intent = {'schemaVersion': 'sermon-release-intent-v1', 'environment': 'dev', 'channel': 'dev', 'project': 'project', 'site': 'site', 'origin': 'https://site.web.app'}
    return intent, data, sha


def v3_only(data):
    """A site that has never published the v4 catalog."""
    return lambda url: (404, b'') if url.endswith('/multilingual-v4.json') else (200, data)


class Remote:
    def __init__(self): self.held = False; self.version = 'old'; self.deleted = False
    def __call__(self, method, url, **kwargs):
        if '/channels/live' in url: return {'release': {'version': {'name': 'sites/site/versions/' + self.version}}}
        if method == 'POST':
            if self.held: raise ValueError('HTTP 412')
            self.held = True
            assert 'ifGenerationMatch=0' in url
            return {'generation': '5'}
        if method == 'GET': return {'generation': '5'}
        if method == 'DELETE':
            assert 'ifGenerationMatch=5' in url
            self.held = False; self.deleted = True
            return {}


def test_remote_lease_success_and_repeat_refusal(tmp_path):
    intent, data, sha = setup(tmp_path); remote = Remote()
    def run(*args, **kwargs): remote.version = 'new'
    args = dict(intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old', baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=run)
    receipt = p.publish(tmp_path, **args)
    assert receipt['status'] == 'deployed' and remote.deleted
    with pytest.raises(ValueError, match='Existing attempt'):
        p.publish(tmp_path, **args)


def test_concurrent_version_change_rebuilds_without_deployment(tmp_path):
    intent, data, sha = setup(tmp_path); remote = Remote(); remote.version = 'other'
    def run(*args, **kwargs): pytest.fail('Deployment must not run')
    with pytest.raises(ValueError, match='Live version changed'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old', baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=run)
    assert remote.deleted
    assert json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())['status'] == 'rebuild_required'


def test_unknown_deploy_retains_lease_and_reconciles_explicitly(tmp_path):
    intent, data, sha = setup(tmp_path); remote = Remote()
    def run(*args, **kwargs):
        remote.version = 'new'
        raise TimeoutError('unknown remote outcome')
    with pytest.raises(TimeoutError):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old', baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=run)
    assert remote.held
    result = p.reconcile(tmp_path, request=remote, reader=v3_only(data), confirmed_version='sites/site/versions/new')
    assert result['status'] == 'deployed' and remote.deleted


def test_live_deployment_heartbeats_and_refuses_reconciliation(tmp_path):
    import os
    import threading

    intent, data, sha = setup(tmp_path)
    remote = Remote()
    observed = {}

    def run(*args, **kwargs):
        path = tmp_path / 'hosting-publisher-progress.json'
        first = json.loads(path.read_text())
        assert first['phase'] == 'deploying'
        assert first['pid'] == os.getpid()
        receipt = json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())
        assert receipt['status'] == 'outcome_unknown'
        assert first['attemptId'] == receipt['attemptId']
        # Wait for a real background heartbeat while subprocess.run is blocked.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = json.loads(path.read_text())
            if current['heartbeatAt'] != first['heartbeatAt']:
                break
            threading.Event().wait(0.005)
        else:
            pytest.fail('No heartbeat while deploy was blocked')
        observed.update(current)
        with pytest.raises(ValueError, match='still running'):
            p.reconcile(tmp_path, request=remote, reader=v3_only(data),
                        confirmed_version='sites/site/versions/new')
        with pytest.raises(ValueError, match='still running'):
            p.publish(tmp_path, intent=intent, routes={'dev': intent},
                      baseline_version='sites/site/versions/old', baseline_catalog_sha=sha,
                      lease_bucket='bucket', request=remote, reader=v3_only(data), run=run)
        assert remote.held and not remote.deleted
        remote.version = 'new'

    receipt = p.publish(tmp_path, intent=intent, routes={'dev': intent},
                        baseline_version='sites/site/versions/old', baseline_catalog_sha=sha,
                        lease_bucket='bucket', request=remote, reader=v3_only(data),
                        run=run, heartbeat_interval=0.01)
    progress = json.loads((tmp_path / 'hosting-publisher-progress.json').read_text())
    assert progress['phase'] == 'completed' and progress['outcome'] == 'deployed'
    assert progress['heartbeatAt'] >= observed['heartbeatAt']
    assert receipt['schemaVersion'] == 'sermon-deployment-attempt-v2'
    assert remote.deleted


def test_unknown_deployment_reports_failed_without_changing_recovery_contract(tmp_path):
    intent, data, sha = setup(tmp_path)
    remote = Remote()

    def run(*args, **kwargs):
        raise TimeoutError('private provider details')

    with pytest.raises(TimeoutError):
        p.publish(tmp_path, intent=intent, routes={'dev': intent},
                  baseline_version='sites/site/versions/old', baseline_catalog_sha=sha,
                  lease_bucket='bucket', request=remote, reader=v3_only(data), run=run)
    progress = json.loads((tmp_path / 'hosting-publisher-progress.json').read_text())
    assert progress['phase'] == 'failed' and progress['outcome'] == 'outcome_unknown'
    assert progress['errorType'] == 'TimeoutError'
    assert 'private provider details' not in json.dumps(progress)
    assert remote.held and not remote.deleted
    with pytest.raises(ValueError, match='Existing attempt'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent},
                  baseline_version='sites/site/versions/old', baseline_catalog_sha=sha,
                  lease_bucket='bucket', request=remote, reader=v3_only(data), run=run)


def test_predeploy_failure_reports_rebuild_required(tmp_path):
    intent, data, sha = setup(tmp_path)
    remote = Remote()
    remote.version = 'other'
    with pytest.raises(ValueError, match='Live version changed'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent},
                  baseline_version='sites/site/versions/old', baseline_catalog_sha=sha,
                  lease_bucket='bucket', request=remote, reader=v3_only(data),
                  run=lambda *args, **kwargs: pytest.fail('No deployment allowed'))
    progress = json.loads((tmp_path / 'hosting-publisher-progress.json').read_text())
    assert progress['phase'] == 'failed' and progress['outcome'] == 'rebuild_required'
    assert remote.deleted


def test_process_crash_releases_local_lock_but_needs_explicit_remote_reconciliation(tmp_path):
    import subprocess
    import sys

    intent, data, sha = setup(tmp_path)
    remote = Remote()
    def interrupted(*args, **kwargs):
        remote.version = 'new'
        raise TimeoutError('unknown')
    with pytest.raises(TimeoutError):
        p.publish(tmp_path, intent=intent, routes={'dev': intent},
                  baseline_version='sites/site/versions/old', baseline_catalog_sha=sha,
                  lease_bucket='bucket', request=remote, reader=v3_only(data), run=interrupted)
    # A separate live owner prevents reconciliation, even with confirmed remote bytes.
    child = subprocess.Popen([sys.executable, '-c',
                              "from scripts.guarded_hosting_publish import publisher_lock\n"
                              "import sys, time\n"
                              "with publisher_lock(sys.argv[1]):\n"
                              "    print('locked', flush=True)\n"
                              "    time.sleep(30)\n", str(tmp_path)],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(ValueError, match='still running'):
            p.reconcile(tmp_path, request=remote, reader=v3_only(data),
                        confirmed_version='sites/site/versions/new')
        assert remote.held
    finally:
        child.kill()
        child.wait(timeout=5)
        child.stdout.close()
    # OS lock recovery does not release the remote generation-fenced lease.
    assert remote.held
    recovered = p.reconcile(tmp_path, request=remote, reader=v3_only(data),
                            confirmed_version='sites/site/versions/new')
    assert recovered['status'] == 'deployed' and remote.deleted


def test_v4_catalog_is_compare_and_swapped_alongside_v3(tmp_path, monkeypatch):
    # Snapshot validation has its own tests; this one covers only the live CAS.
    monkeypatch.setattr(p.contract, 'validate_catalog_snapshot', lambda snapshot: None)
    intent, data, sha = setup(tmp_path); remote = Remote()
    v4 = b'{"schemaVersion": "sermon-multilingual-catalog-v4"}'
    report = json.loads((tmp_path / 'seal-report.json').read_text())
    report['catalogV4Sha256'] = hashlib.sha256(v4).hexdigest()
    (tmp_path / 'seal-report.json').write_text(json.dumps(report))
    live = {'v4': None}
    def reader(url):
        if url.endswith('/multilingual-v4.json'):
            return (404, b'') if live['v4'] is None else (200, live['v4'])
        return 200, data
    def stale(*args, **kwargs): pytest.fail('Deployment must not run against a changed v4 catalog')
    live['v4'] = b'{"other": true}'
    with pytest.raises(ValueError, match='Live v4 catalog changed'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=reader, run=stale)
    (tmp_path / 'deployment-attempt-v2.json').unlink()
    live['v4'] = None
    def deploy(*args, **kwargs):
        remote.version = 'new'; live['v4'] = v4
    receipt = p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                        baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=reader, run=deploy)
    assert receipt['status'] == 'deployed'
    # A later publication starts from the live v4 catalog it was built on.
    (tmp_path / 'deployment-attempt-v2.json').unlink()
    remote.version = 'old'
    with pytest.raises(ValueError, match='Live v4 catalog changed'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=reader, run=stale)


def test_published_v4_readback_must_match_the_sealed_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(p.contract, 'validate_catalog_snapshot', lambda snapshot: None)
    intent, data, sha = setup(tmp_path); remote = Remote()
    report = json.loads((tmp_path / 'seal-report.json').read_text())
    report['catalogV4Sha256'] = 'f' * 64
    (tmp_path / 'seal-report.json').write_text(json.dumps(report))
    def deploy(*args, **kwargs): remote.version = 'new'
    with pytest.raises(ValueError, match='Published v4 catalog readback differs'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=deploy)
