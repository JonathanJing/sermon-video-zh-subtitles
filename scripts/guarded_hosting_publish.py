"""Hosting publisher with remote generation-fenced lease and immutable live baseline.

All publishers for a site must use the same bucket/object lease. A crash leaves
it held for explicit reconciliation; elapsed time never authorizes stealing it.
External Firebase console publishers cannot be fenced by a GCS lease, so live
version is checked again before and after deployment.
"""
from __future__ import annotations
import argparse
import hashlib
import fcntl
import os
import socket
import threading
import time
from contextlib import contextmanager
import json
import subprocess
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone
# Nested v3 validators import the scripts package, including direct CLI runs.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts import delivery_contract as contract
    from scripts.sermon_execution_harness import atomic_json
except ImportError:
    import delivery_contract as contract
    from sermon_execution_harness import atomic_json


@contextmanager
def publisher_lock(snapshot):
    """Local process lock complements the remote lease; crashes release only this lock."""
    with (Path(snapshot) / 'hosting-publisher.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Publisher is still running; wait for completion before reconciliation') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class PublisherProgress:
    """Operational progress only; never substitutes for the deployment receipt."""
    def __init__(self, snapshot, attempt_id):
        self.path = Path(snapshot) / 'hosting-publisher-progress.json'
        self.started = time.monotonic()
        self.state = {'schemaVersion': 'sermon-hosting-publisher-progress-v1',
                      'attemptId': attempt_id, 'pid': os.getpid(), 'hostname': socket.gethostname(),
                      'startedAt': datetime.now(timezone.utc).isoformat()}
        self.lock = threading.Lock()

    def update(self, phase, **fields):
        with self.lock:
            self.state.update(phase=phase, heartbeatAt=datetime.now(timezone.utc).isoformat(),
                              elapsedSeconds=round(time.monotonic() - self.started, 3), **fields)
            atomic_json(self.path, self.state)

    @contextmanager
    def heartbeat(self, interval):
        stop = threading.Event()
        errors = []
        def beat():
            while not stop.wait(interval):
                try:
                    self.update('deploying')
                except BaseException as exc:
                    errors.append(exc)
                    return
        worker = threading.Thread(target=beat, daemon=True)
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join()
        if errors:
            raise errors[0]


def authenticated_transport():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    session = AuthorizedSession(credentials)
    def request(method, url, *, data=None, headers=None):
        response = session.request(method, url, data=data, headers=headers, timeout=60)
        # Never return authentication headers or provider error bodies.
        if response.status_code not in (200, 201, 204):
            raise ValueError(f'Remote operation rejected: HTTP {response.status_code}')
        return response.json() if response.content else {}
    return request


class RemoteLease:
    def __init__(self, request, bucket, site):
        self.request = request
        self.name = 'sermon-publisher-leases/' + site + '.json'
        self.bucket = bucket
        self.object_url = 'https://storage.googleapis.com/storage/v1/b/' + quote(bucket, safe='') + '/o/' + quote(self.name, safe='')
        self.generation = None

    def acquire(self, attempt):
        url = 'https://storage.googleapis.com/upload/storage/v1/b/' + quote(self.bucket, safe='') + '/o?uploadType=media&ifGenerationMatch=0&name=' + quote(self.name, safe='')
        result = self.request('POST', url, data=json.dumps(attempt).encode(), headers={'Content-Type': 'application/json'})
        self.generation = str(result['generation'])
        return self.generation

    def check(self):
        result = self.request('GET', self.object_url)
        contract.require(str(result['generation']) == self.generation, 'Publisher lease ownership changed')

    def release(self):
        contract.require(self.generation is not None, 'Lease is not held')
        self.request('DELETE', self.object_url + '?ifGenerationMatch=' + self.generation)


def live_version(request, site):
    result = request('GET', 'https://firebasehosting.googleapis.com/v1beta1/sites/' + quote(site, safe='') + '/channels/live')
    # Site release lists include preview channels; Channel.release is the actual live head.
    name = result.get('release', {}).get('version', {}).get('name')
    contract.require(isinstance(name, str) and name.startswith('sites/' + site + '/versions/'), 'Live Hosting version unavailable')
    return name


def public_catalog(reader, origin):
    status, data = reader(origin + '/multilingual-v3.json')
    contract.require(status == 200, 'Live catalog cannot be read')
    return hashlib.sha256(data).hexdigest()


def publish(snapshot, *, intent, routes, baseline_version, baseline_catalog_sha,
            lease_bucket, request, reader, run=subprocess.run, heartbeat_interval=5):
    contract.require(heartbeat_interval > 0, 'Heartbeat interval must be positive')
    with publisher_lock(snapshot):
        return _publish(snapshot, intent=intent, routes=routes, baseline_version=baseline_version,
                        baseline_catalog_sha=baseline_catalog_sha, lease_bucket=lease_bucket,
                        request=request, reader=reader, run=run, heartbeat_interval=heartbeat_interval)


def _publish(snapshot, *, intent, routes, baseline_version, baseline_catalog_sha,
             lease_bucket, request, reader, run, heartbeat_interval):
    snapshot = Path(snapshot)
    contract.validate_intent(intent, routes)
    contract.validate_catalog_snapshot(snapshot)
    report = json.loads((snapshot / 'seal-report.json').read_text())
    receipt_path = snapshot / 'deployment-attempt-v2.json'
    contract.require(not receipt_path.exists(), 'Existing attempt requires reconciliation; never retry an unknown deployment')
    attempt = contract.new_attempt(intent, catalog_sha=report['catalogSha256'],
                                   assets_sha=contract.sha(report['files']), baseline_version=baseline_version)
    lease = RemoteLease(request, lease_bucket, intent['site'])
    attempt['leaseGeneration'] = lease.acquire({'attemptId': attempt['attemptId'], 'intent': intent, 'baselineVersion': baseline_version})
    attempt['leaseBucket'] = lease_bucket
    atomic_json(receipt_path, attempt)
    deploying = False
    progress = PublisherProgress(snapshot, attempt['attemptId'])
    try:
        progress.update('checking_baseline')
        contract.require(live_version(request, intent['site']) == baseline_version, 'Live version changed; rebuild against current snapshot')
        contract.require(public_catalog(reader, intent['origin']) == baseline_catalog_sha, 'Live catalog changed; rebuild against current snapshot')
        # Preserve the candidate hosting headers/rewrites, bind its public root and exact site.
        config_path = snapshot / 'firebase.json'
        config = json.loads(config_path.read_text()) if config_path.exists() else {'hosting': {}}
        contract.require(isinstance(config.get('hosting'), dict), 'Exactly one Hosting configuration required')
        config['hosting'].pop('target', None)
        config['hosting'].update(site=intent['site'], public=str((snapshot / 'public').resolve()))
        bound_config = snapshot / 'firebase-bound.json'
        atomic_json(bound_config, config)
        lease.check()
        contract.require(live_version(request, intent['site']) == baseline_version, 'Concurrent publication detected')
        attempt['status'] = 'outcome_unknown'
        atomic_json(receipt_path, attempt)
        progress.update('deploying')
        deploying = True
        with progress.heartbeat(heartbeat_interval), (snapshot / 'hosting-publish.log').open('w') as log:
            run(['firebase', 'deploy', '--only', 'hosting', '--project', intent['project'], '--config', str(bound_config.resolve()), '--non-interactive', '--json'],
                cwd=snapshot, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
        progress.update('verifying_readback')
        lease.check()
        version = live_version(request, intent['site'])
        contract.require(version != baseline_version, 'No new Hosting version observed')
        contract.require(public_catalog(reader, intent['origin']) == attempt['catalogSha256'], 'Published catalog readback differs')
        attempt.update(newVersion=version, completedAt=datetime.now(timezone.utc).isoformat(), status='deployed')
        atomic_json(receipt_path, attempt)
        lease.release()
        progress.update('completed', outcome=attempt['status'])
        return attempt
    except BaseException as exc:
        if not deploying:
            attempt.update(status='rebuild_required', completedAt=datetime.now(timezone.utc).isoformat())
            atomic_json(receipt_path, attempt)
            lease.release()
        # Failure details stay in the existing CLI log, not the public progress record.
        try:
            progress.update('failed', outcome=attempt['status'], errorType=type(exc).__name__)
        except Exception:
            pass  # Progress failure must not replace the original deployment error.
        # Once deployment may have started, retain the remote lease and unknown receipt.
        raise


def reconcile(snapshot, *, request, reader, confirmed_version):
    """Explicitly reconcile an uncertain attempt; never starts another deployment."""
    with publisher_lock(snapshot):
        return _reconcile(snapshot, request=request, reader=reader, confirmed_version=confirmed_version)


def _reconcile(snapshot, *, request, reader, confirmed_version):
    path = Path(snapshot) / 'deployment-attempt-v2.json'
    attempt = json.loads(path.read_text())
    contract.require(attempt['status'] in ('outcome_unknown', 'deployed'), 'Only unknown attempts need reconciliation')
    lease = RemoteLease(request, attempt['leaseBucket'], attempt['intent']['site'])
    lease.generation = attempt['leaseGeneration']
    if attempt['status'] == 'deployed':
        # Deployment is already verified; only a failed lease release is left to retry.
        try:
            lease.check()
        except ValueError as exc:
            if 'HTTP 404' in str(exc):
                return attempt  # Lease already released.
            raise
        lease.release()
        return attempt
    lease.check()
    observed = live_version(request, attempt['intent']['site'])
    contract.require(observed == confirmed_version and observed != attempt['baselineVersion'], 'Explicit confirmed new version differs')
    contract.require(public_catalog(reader, attempt['intent']['origin']) == attempt['catalogSha256'], 'Remote catalog differs; manual recovery required')
    attempt.update(status='deployed', newVersion=observed, completedAt=datetime.now(timezone.utc).isoformat())
    atomic_json(path, attempt)
    lease.release()
    return attempt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    contract.validate_intent(config['intent'], config['routes'])
    contract.validate_catalog_snapshot(config['snapshot'])
    if not args.execute:
        print(json.dumps({'status': 'validated_not_deployed'}))
        return
    import urllib.request
    def reader(url):
        with urllib.request.urlopen(urllib.request.Request(url, headers={'Cache-Control': 'no-cache'}), timeout=60) as response:
            return response.status, response.read()
    result = publish(**config, request=authenticated_transport(), reader=reader)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
