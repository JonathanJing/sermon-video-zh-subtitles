import hashlib
import json
from pathlib import Path
import pytest
import time
from scripts import guarded_hosting_publish as p
from tongxing_production.storage import hosting


def write_deploy_result(kwargs, version='sites/site/versions/new'):
    """Injected run follows the real firebase --json stdout contract."""
    json.dump({'status': 'success', 'result': {'hosting': version}}, kwargs['stdout'])


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
    def run(*args, **kwargs): remote.version = 'new'; write_deploy_result(kwargs)
    args = dict(intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old', baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=run)
    receipt = p.publish(tmp_path, **args)
    assert receipt['status'] == 'deployed' and remote.deleted
    with pytest.raises(ValueError, match='Existing attempt'):
        p.publish(tmp_path, **args)


def test_default_runner_is_the_host_firebase_cli_with_the_recorded_argv(tmp_path, monkeypatch):
    # D3: without an injected run, publish uses the Hosting adapter's runner,
    # which calls subprocess.run with the same argv and options as before the move.
    import subprocess
    intent, data, sha = setup(tmp_path); remote = Remote(); calls = []
    def deploy(argv, **kwargs):
        calls.append((argv, {k: v for k, v in kwargs.items() if k not in ('stdout', 'stderr')}))
        remote.version = 'new'; write_deploy_result(kwargs)
    monkeypatch.setattr(subprocess, 'run', deploy)
    receipt = p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                        baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data))
    assert receipt['status'] == 'deployed'
    assert calls == [(['firebase', 'deploy', '--only', 'hosting', '--project', 'project', '--config',
                       str((tmp_path / 'firebase-bound.json').resolve()), '--non-interactive', '--json'],
                      {'cwd': tmp_path, 'check': True, 'timeout': 3600})]


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
        remote.version = 'new'; write_deploy_result(kwargs)
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
        remote.version = 'new'; write_deploy_result(kwargs)

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
        remote.version = 'new'; write_deploy_result(kwargs)
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
        remote.version = 'new'; write_deploy_result(kwargs); live['v4'] = v4
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
    def deploy(*args, **kwargs): remote.version = 'new'; write_deploy_result(kwargs)
    with pytest.raises(ValueError, match='Published v4 catalog readback differs'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=deploy)


def test_await_propagation_retries_reads_until_they_pass_or_the_deadline():
    now, sleeps, calls = [0.0], [], []
    def clock(): return now[0]
    def sleep(seconds): sleeps.append(seconds); now[0] += seconds
    def eventually():
        calls.append(1)
        p.contract.require(len(calls) >= 3, 'stale')
        return 'fresh'
    assert p.await_propagation(eventually, timeout=30, interval=5, sleep=sleep, clock=clock) == 'fresh'
    assert sleeps == [5, 5]
    calls.clear(); sleeps.clear(); now[0] = 0.0
    def never(): calls.append(1); raise ValueError('still stale')
    with pytest.raises(ValueError, match='still stale'):
        p.await_propagation(never, timeout=12, interval=5, sleep=sleep, clock=clock)
    assert sleeps == [5, 5] and len(calls) == 3


def test_a_v4_catalog_that_reads_back_stale_at_first_is_deployed_once_it_propagates(tmp_path, monkeypatch):
    # 2026-10-13 Dev: the v4 catalog read back stale right after a successful deploy and the
    # attempt was left outcome_unknown, needing a manual reconcile.
    monkeypatch.setattr(p.contract, 'validate_catalog_snapshot', lambda snapshot: None)
    monkeypatch.setattr(p, 'PROPAGATION_TIMEOUT_SECONDS', 60.0)
    monkeypatch.setattr(p.time, 'sleep', lambda seconds: None)
    intent, data, sha = setup(tmp_path); remote = Remote()
    v4 = b'{"schemaVersion": "sermon-multilingual-catalog-v4"}'
    report = json.loads((tmp_path / 'seal-report.json').read_text())
    report['catalogV4Sha256'] = hashlib.sha256(v4).hexdigest()
    (tmp_path / 'seal-report.json').write_text(json.dumps(report))
    reads = {'v4': 0}
    def reader(url):
        if url.endswith('/multilingual-v4.json'):
            reads['v4'] += 1
            # Before the deploy: none yet. Just after: the CDN still serves an older v4 twice.
            if remote.version != 'new':
                return 404, b''
            return (200, b'{"stale": true}') if reads['v4'] <= 3 else (200, v4)
        return 200, data
    def deploy(*args, **kwargs): remote.version = 'new'; write_deploy_result(kwargs)
    receipt = p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                        baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=reader, run=deploy)
    assert receipt['status'] == 'deployed' and receipt['newVersion'] == 'sites/site/versions/new'
    assert reads['v4'] >= 4


def test_runtime_sleep_and_clock_injection(monkeypatch):
    from types import SimpleNamespace
    now, slept, calls = [0.0], [], []
    def sleep(seconds): slept.append(seconds); now[0] += seconds
    monkeypatch.setattr(p, 'time', SimpleNamespace(sleep=sleep, monotonic=lambda: now[0]))
    def check():
        calls.append(1)
        if len(calls) < 3: raise ValueError('stale')
        return 'fresh'
    assert p.await_propagation(check, timeout=20) == 'fresh'
    assert slept == [5, 5]


def test_read_budget_decreases_and_expired_success_is_rejected():
    now, seen = [0.0], []
    def request(method, url, *, timeout):
        seen.append(timeout); now[0] += 4
        return {'release': {'version': {'name': 'sites/site/versions/new'}}}
    def reader(url, *, timeout):
        seen.append(timeout); now[0] += 4
        return 200, b'fresh'
    def check():
        p.live_version(request, 'site')
        p.public_catalog(reader, 'https://site.web.app')
        p.public_catalog_v4(reader, 'https://site.web.app')
        return 'too late'
    with pytest.raises(TimeoutError, match='deadline expired'):
        p.await_propagation(check, timeout=10, clock=lambda: now[0], sleep=lambda seconds: None)
    assert seen == [10, 6, 2]
    # Context is reset even when the read failed.
    assert p.remaining_read_timeout(60) == 60


def test_deadline_stops_the_next_read_before_it_starts():
    now, calls = [0.0], []
    def reader(url, *, timeout): calls.append(timeout); now[0] = 11; return 200, b'fresh'
    def check():
        p.public_catalog(reader, 'https://site.web.app')
        p.public_catalog(reader, 'https://site.web.app')
    with pytest.raises(TimeoutError):
        p.await_propagation(check, timeout=10, clock=lambda: now[0])
    assert calls == [10]


@pytest.mark.parametrize('race', ['between_retries', 'during_catalogs', 'to_baseline'])
def test_external_version_race_keeps_first_version_unknown_and_never_redeploys(tmp_path, monkeypatch, race):
    intent, data, sha = setup(tmp_path); remote = Remote(); deployments = []
    monkeypatch.setattr(p, 'PROPAGATION_TIMEOUT_SECONDS', 30)
    monkeypatch.setattr(p.time, 'sleep', lambda seconds: None)
    def deploy(*args, **kwargs): deployments.append(1); remote.version = 'new'; write_deploy_result(kwargs)
    def reader(url, *, timeout=60):
        if remote.version == 'new' and url.endswith('/multilingual-v3.json'):
            remote.version = 'old' if race == 'to_baseline' else 'external'
            return (200, b'stale') if race != 'during_catalogs' else (200, data)
        return v3_only(data)(url)
    args = dict(intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=reader, run=deploy)
    with pytest.raises(p.PublicationVersionChanged): p.publish(tmp_path, **args)
    receipt = json.loads((tmp_path/'deployment-attempt-v2.json').read_text())
    assert receipt['status'] == 'outcome_unknown' and receipt['newVersion'] == 'sites/site/versions/new'
    assert remote.held and deployments == [1]
    with pytest.raises(ValueError, match='Existing attempt'): p.publish(tmp_path, **args)
    with pytest.raises(ValueError, match='first observed'):
        p.reconcile(tmp_path, request=remote, reader=reader, confirmed_version='sites/site/versions/external')
    assert remote.held and deployments == [1]


def test_incomplete_read_retries_catalog_get_without_repeating_deploy(tmp_path, monkeypatch):
    import http.client
    intent, data, sha = setup(tmp_path); remote = Remote(); deployments, failures = [], []
    monkeypatch.setattr(p, 'PROPAGATION_TIMEOUT_SECONDS', 30)
    monkeypatch.setattr(p.time, 'sleep', lambda seconds: None)
    def deploy(*args, **kwargs): deployments.append(1); remote.version = 'new'; write_deploy_result(kwargs)
    def reader(url, *, timeout=60):
        if remote.version == 'new' and not failures:
            failures.append(1); raise http.client.IncompleteRead(b'partial', 20)
        return v3_only(data)(url)
    result = p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                       baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=reader, run=deploy)
    assert result['status'] == 'deployed' and result['newVersion'] == 'sites/site/versions/new'
    assert deployments == [1] and failures == [1] and remote.deleted


def test_publish_late_read_success_retains_unknown_and_lease(tmp_path, monkeypatch):
    from types import SimpleNamespace
    now = [0.0]
    monkeypatch.setattr(p, 'time', SimpleNamespace(sleep=lambda seconds: None, monotonic=lambda: now[0]))
    monkeypatch.setattr(p, 'PROPAGATION_TIMEOUT_SECONDS', 10)
    intent, data, sha = setup(tmp_path); remote = Remote(); deployments = []
    def deploy(*args, **kwargs): deployments.append(1); remote.version = 'new'; write_deploy_result(kwargs)
    def reader(url, *, timeout=60):
        if remote.version == 'new': now[0] = 11
        return v3_only(data)(url)
    with pytest.raises(TimeoutError):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=reader, run=deploy)
    assert json.loads((tmp_path/'deployment-attempt-v2.json').read_text())['status'] == 'outcome_unknown'
    assert remote.held and deployments == [1]


def test_zero_budget_does_not_start_a_read():
    calls = []
    with pytest.raises(ValueError, match='must be positive'):
        p.await_propagation(lambda: calls.append(1), timeout=0)
    assert calls == []


def test_reconciliation_rejects_version_change_after_catalog_read(tmp_path, monkeypatch):
    intent, data, sha = setup(tmp_path); remote = Remote()
    def deploy(*args, **kwargs): remote.version = 'new'; write_deploy_result(kwargs); raise TimeoutError('unknown')
    with pytest.raises(TimeoutError):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=deploy)
    def reader(url): remote.version = 'external'; return v3_only(data)(url)
    with pytest.raises(p.PublicationVersionChanged):
        p.reconcile(tmp_path, request=remote, reader=reader, confirmed_version='sites/site/versions/new')
    assert remote.held and json.loads((tmp_path/'deployment-attempt-v2.json').read_text())['status'] == 'outcome_unknown'


def test_external_deploy_before_first_readback_cannot_be_claimed(tmp_path, monkeypatch):
    intent, data, sha = setup(tmp_path); remote = Remote(); deployments = []
    def deploy(*args, **kwargs):
        deployments.append(1)
        write_deploy_result(kwargs)  # Our CLI produced new; a console publisher wins immediately afterward.
        remote.version = 'external'
    def request(method, url, **kwargs):
        if '/channels/live' in url and remote.version == 'external':
            receipt = json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())
            assert receipt['newVersion'] == 'sites/site/versions/new'
        return remote(method, url, **kwargs)
    monkeypatch.setattr(p.time, 'sleep', lambda seconds: pytest.fail('Version conflict is not retryable'))
    with pytest.raises(p.PublicationVersionChanged, match='deployment receipt'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=request, reader=v3_only(data), run=deploy)
    receipt = json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())
    assert receipt['status'] == 'outcome_unknown' and receipt['newVersion'] == 'sites/site/versions/new'
    assert deployments == [1] and remote.held and not remote.deleted
    with pytest.raises(ValueError, match='recorded deployment version'):
        p.reconcile(tmp_path, request=remote, reader=v3_only(data), confirmed_version='sites/site/versions/external')


@pytest.mark.parametrize('output', [None, {}, {'status': 'error', 'result': {'hosting': 'sites/site/versions/new'}},
    {'status': 'success', 'result': {}},
    {'status': 'success', 'result': {'hosting': ['sites/site/versions/new', 'sites/other/versions/other']}},
    {'status': 'success', 'result': {'hosting': 'sites/other/versions/new'}},
    {'status': 'success', 'result': {'hosting': 'sites/site/versions/old'}},
    {'status': 'success', 'result': {'hosting': 'sites/site/versions/'}},
    {'status': 'success', 'result': {'hosting': 'projects/1/sites/other/versions/new'}},
    {'status': 'success', 'result': {'hosting': 'projects//sites/site/versions/new'}},
    {'status': 'success', 'result': {'hosting': 'projects/1/2/sites/site/versions/new'}},
    {'status': 'success', 'result': {'hosting': 'projects/1/sites/site/versions/old'}}])
def test_missing_or_invalid_cli_identity_keeps_unknown_without_claiming_live_version(tmp_path, output):
    intent, data, sha = setup(tmp_path); remote = Remote(); deployments = []
    def deploy(*args, **kwargs):
        deployments.append(1); remote.version = 'new'
        if output is not None: json.dump(output, kwargs['stdout'])
    with pytest.raises(ValueError, match='receipt|Exactly one'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=deploy)
    receipt = json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())
    assert receipt['status'] == 'outcome_unknown' and receipt['newVersion'] is None
    assert deployments == [1] and remote.held


def test_cli_owned_version_can_wait_for_baseline_control_plane_propagation(tmp_path, monkeypatch):
    intent, data, sha = setup(tmp_path); remote = Remote(); deployments, sleeps = [], []
    monkeypatch.setattr(p, 'PROPAGATION_TIMEOUT_SECONDS', 30)
    def sleep(seconds): sleeps.append(seconds); remote.version = 'new'
    monkeypatch.setattr(p.time, 'sleep', sleep)
    def deploy(*args, **kwargs): deployments.append(1); write_deploy_result(kwargs)
    receipt = p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                        baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=deploy)
    assert receipt['status'] == 'deployed' and receipt['newVersion'] == 'sites/site/versions/new'
    assert deployments == [1] and sleeps == [5]


@pytest.mark.parametrize('hosting', ['projects/548454657719/sites/site/versions/new',
                                     ['projects/ai-for-god-sermon-audio-dev/sites/site/versions/new']])
def test_project_qualified_cli_receipt_names_the_site_version(tmp_path, hosting):
    # firebase-tools 15.30.2 on the 2026-10-14 Dev deploy returned the project-qualified name.
    path = tmp_path / 'result.json'
    path.write_text(json.dumps({'status': 'success', 'result': {'hosting': hosting}}))
    assert p.deployed_version(path, site='site', baseline_version='sites/site/versions/old') == 'sites/site/versions/new'


def test_single_version_array_cli_receipt_is_accepted(tmp_path):
    path = tmp_path / 'result.json'
    path.write_text(json.dumps({'status': 'success', 'result': {'hosting': ['sites/site/versions/new']}}))
    assert p.deployed_version(path, site='site', baseline_version='sites/site/versions/old') == 'sites/site/versions/new'


def pending_cli_attempt(tmp_path, monkeypatch, *, observed=False):
    """One fake deploy, then a crash before readback or after observing own head."""
    intent, data, sha = setup(tmp_path); remote = Remote(); deployments = []
    def deploy(*args, **kwargs):
        deployments.append(1); write_deploy_result(kwargs)
        if observed:
            remote.version = 'new'
    with monkeypatch.context() as patch:
        def interrupted(check):
            if observed:
                # Observe the owned head, then crash while fetching its catalog.
                check()
            raise TimeoutError('process interrupted before observation')
        patch.setattr(p, 'await_propagation', interrupted)
        def reader(url):
            if observed and remote.version == 'new':
                saved = json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())
                assert saved['versionPropagation']['ownedVersionObserved'] is True
                raise TimeoutError('crash after durable observation')
            return v3_only(data)(url)
        with pytest.raises(TimeoutError):
            p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                      baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=reader, run=deploy)
    saved = json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())
    assert saved['versionPropagation']['ownedVersionObserved'] is observed
    assert remote.held and deployments == [1]
    return remote, data, deployments


def fake_propagation_clock(monkeypatch, on_sleep=lambda: None):
    now, sleeps = [0.0], []
    def sleep(seconds):
        now[0] += seconds; sleeps.append(seconds); on_sleep()
    monkeypatch.setattr(p.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(p.time, 'sleep', sleep)
    monkeypatch.setattr(p, 'PROPAGATION_TIMEOUT_SECONDS', 12)
    return now, sleeps


def test_reconcile_waits_for_pinned_owned_version_without_deploying_again(tmp_path, monkeypatch):
    remote, data, deployments = pending_cli_attempt(tmp_path, monkeypatch)
    _, sleeps = fake_propagation_clock(monkeypatch, lambda: setattr(remote, 'version', 'new'))
    result = p.reconcile(tmp_path, request=remote, reader=v3_only(data), confirmed_version='sites/site/versions/new')
    assert result['status'] == 'deployed' and result['versionPropagation']['ownedVersionObserved'] is True
    assert sleeps == [5] and deployments == [1] and remote.deleted


def test_reconcile_baseline_deadline_keeps_unknown_lease_and_single_deploy(tmp_path, monkeypatch):
    remote, data, deployments = pending_cli_attempt(tmp_path, monkeypatch)
    _, sleeps = fake_propagation_clock(monkeypatch)
    with pytest.raises(ValueError, match='not propagated'):
        p.reconcile(tmp_path, request=remote, reader=v3_only(data), confirmed_version='sites/site/versions/new')
    assert sleeps == [5, 5] and remote.held and not remote.deleted and deployments == [1]
    saved = json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())
    assert saved['status'] == 'outcome_unknown' and saved['versionPropagation']['ownedVersionObserved'] is False


@pytest.mark.parametrize('observed,version', [(False, 'external'), (True, 'old'), (True, 'external')])
def test_reconcile_conflicts_never_retry_even_across_observed_crash(tmp_path, monkeypatch, observed, version):
    remote, data, deployments = pending_cli_attempt(tmp_path, monkeypatch, observed=observed)
    remote.version = version
    _, sleeps = fake_propagation_clock(monkeypatch)
    with pytest.raises(p.PublicationVersionChanged):
        p.reconcile(tmp_path, request=remote, reader=v3_only(data), confirmed_version='sites/site/versions/new')
    assert sleeps == [] and remote.held and not remote.deleted and deployments == [1]


@pytest.mark.parametrize('mutation', ['legacy', 'null', 'copied-attempt', 'wrong-owned', 'invalid-boolean', 'unknown-schema'])
def test_propagation_state_cannot_upgrade_legacy_or_change_its_pinned_version(tmp_path, monkeypatch, mutation):
    remote, data, deployments = pending_cli_attempt(tmp_path, monkeypatch)
    path = tmp_path / 'deployment-attempt-v2.json'; saved = json.loads(path.read_text())
    if mutation == 'legacy':
        saved.pop('versionPropagation')
    elif mutation == 'null':
        saved['versionPropagation'] = None
    elif mutation == 'copied-attempt':
        saved['versionPropagation']['attemptId'] = 'another-attempt'
    elif mutation == 'wrong-owned':
        saved['versionPropagation']['ownedVersion'] = 'sites/site/versions/external'
    elif mutation == 'invalid-boolean':
        saved['versionPropagation']['ownedVersionObserved'] = 0
    else:
        saved['versionPropagation']['schemaVersion'] = 'unknown'
    path.write_text(json.dumps(saved)); _, sleeps = fake_propagation_clock(monkeypatch)
    with pytest.raises(ValueError):
        p.reconcile(tmp_path, request=remote, reader=v3_only(data), confirmed_version='sites/site/versions/new')
    with pytest.raises(ValueError, match='recorded deployment version'):
        p.reconcile(tmp_path, request=remote, reader=v3_only(data), confirmed_version='sites/site/versions/external')
    assert sleeps == [] and deployments == [1] and remote.held
    assert json.loads(path.read_text()) == saved


@pytest.mark.parametrize('recovery', [False, True])
def test_deployed_receipt_directory_is_synced_before_lease_release(tmp_path, monkeypatch, recovery):
    persisted = []
    original = p._persist_attempt
    def persist(path, attempt):
        original(path, attempt)
        persisted.append(attempt['status'])
    if recovery:
        remote, data, _ = pending_cli_attempt(tmp_path, monkeypatch)
        remote.version = 'new'
    else:
        intent, data, sha = setup(tmp_path); remote = Remote()
    monkeypatch.setattr(p, '_persist_attempt', persist)
    original_release = hosting.RemoteLease.release
    def release(lease):
        assert persisted[-1] == 'deployed'
        assert json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())['status'] == 'deployed'
        original_release(lease)
    monkeypatch.setattr(hosting.RemoteLease, 'release', release)
    if recovery:
        p.reconcile(tmp_path, request=remote, reader=v3_only(data), confirmed_version='sites/site/versions/new')
    else:
        def deploy(*args, **kwargs): remote.version = 'new'; write_deploy_result(kwargs)
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old',
                  baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=v3_only(data), run=deploy)
    assert remote.deleted
