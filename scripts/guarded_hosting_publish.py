"""Hosting publisher with remote generation-fenced lease and immutable live baseline.

All publishers for a site must use the same bucket/object lease. A crash leaves
it held for explicit reconciliation; elapsed time never authorizes stealing it.
External Firebase console publishers cannot be fenced by a GCS lease, so live
version is checked again before and after deployment.
"""
from __future__ import annotations
import argparse
import hashlib
import http.client
import inspect
from contextvars import ContextVar
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
    def request(method, url, *, data=None, headers=None, timeout=60):
        response = session.request(method, url, data=data, headers=headers, timeout=timeout)
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


# Hosting serves a new version through its CDN a little after the deploy returns: on
# 2026-10-13 a file 404'd 3.5 s after an asset deploy and the v4 catalog read back stale,
# leaving a deployment that had succeeded marked outcome_unknown. Read-only checks of a
# fresh deployment are therefore repeated until they pass or this deadline passes.
PROPAGATION_TIMEOUT_SECONDS = 120.0
PROPAGATION_INTERVAL_SECONDS = 5.0


_READ_DEADLINE = ContextVar('hosting_read_deadline', default=None)


class PublicationVersionChanged(ValueError):
    """A competing version cannot become this attempt's publication evidence."""


def remaining_read_timeout(maximum):
    budget = _READ_DEADLINE.get()
    if budget is None:
        return maximum
    deadline, clock = budget
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError('Hosting propagation deadline expired')
    return min(maximum, remaining)


def _read_with_budget(read, *args):
    # Production transports accept timeout. Legacy injected readers may not; their
    # result still must complete before the outer deadline to be accepted.
    timeout = remaining_read_timeout(60)
    if _READ_DEADLINE.get() is not None:
        parameters = inspect.signature(read).parameters.values()
        if any(p.name == 'timeout' or p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters):
            return read(*args, timeout=timeout)
    return read(*args)


def await_propagation(check, *, timeout=None, interval=None, sleep=None, clock=None):
    """Retry reads only within one deadline, including completed-result validation."""
    timeout = PROPAGATION_TIMEOUT_SECONDS if timeout is None else timeout
    interval = PROPAGATION_INTERVAL_SECONDS if interval is None else interval
    sleep = time.sleep if sleep is None else sleep
    clock = time.monotonic if clock is None else clock
    contract.require(timeout > 0 and interval > 0, 'Propagation timeout and interval must be positive')
    deadline = clock() + timeout
    token = _READ_DEADLINE.set((deadline, clock))
    try:
        while True:
            remaining_read_timeout(timeout)
            try:
                result = check()
                remaining_read_timeout(timeout)  # Never accept success completed after expiry.
                return result
            except PublicationVersionChanged:
                raise
            except (ValueError, OSError, http.client.HTTPException):
                if clock() + interval >= deadline:
                    raise
                sleep(interval)
    finally:
        _READ_DEADLINE.reset(token)


def live_version(request, site):
    result = _read_with_budget(request, 'GET', 'https://firebasehosting.googleapis.com/v1beta1/sites/' + quote(site, safe='') + '/channels/live')
    # Site release lists include preview channels; Channel.release is the actual live head.
    name = result.get('release', {}).get('version', {}).get('name')
    contract.require(isinstance(name, str) and name.startswith('sites/' + site + '/versions/'), 'Live Hosting version unavailable')
    return name


def public_catalog(reader, origin):
    status, data = _read_with_budget(reader, origin + '/multilingual-v3.json')
    contract.require(status == 200, 'Live catalog cannot be read')
    return hashlib.sha256(data).hexdigest()


def public_catalog_v4(reader, origin):
    """Live v4 catalog hash, or None while the site has never published one."""
    from urllib.error import HTTPError
    try:
        status, data = _read_with_budget(reader, origin + '/multilingual-v4.json')
    except HTTPError as error:
        status, data = error.code, b''
    if status == 404:
        return None
    contract.require(status == 200, 'Live v4 catalog cannot be read')
    return hashlib.sha256(data).hexdigest()


def deployed_version(result_path, *, site, baseline_version):
    """Parse firebase-tools deploy --json's own single-site version receipt.

    firebase-tools 15.30.2 lib/deploy/index.js returns {hosting: versionName}
    (an array for multiple sites); lib/command.js wraps it in status/result.
    Injected subprocess runners must write this same JSON to their stdout file.
    An observed live head is never evidence of which version this command made.
    """
    try:
        receipt = json.loads(Path(result_path).read_text())
    except (OSError, ValueError) as error:
        raise ValueError('Deployment version receipt unavailable; explicit reconciliation required') from error
    contract.require(isinstance(receipt, dict) and receipt.get('status') == 'success'
                     and isinstance(receipt.get('result'), dict), 'Invalid deployment version receipt')
    version = receipt['result'].get('hosting')
    if isinstance(version, list):
        contract.require(len(version) == 1, 'Exactly one deployed Hosting version required')
        version = version[0]
    prefix = 'sites/' + site + '/versions/'
    contract.require(isinstance(version, str) and version.startswith(prefix)
                     and bool(version[len(prefix):]) and '/' not in version[len(prefix):]
                     and not any(character.isspace() for character in version)
                     and version != baseline_version, 'Deployment version receipt differs from intended site or baseline')
    return version


PROPAGATION_STATE_SCHEMA = 'sermon-hosting-version-propagation-v1'


def _persist_attempt(path, attempt):
    atomic_json(path, attempt)
    # The observed flag must survive a crash before any retry/reconciliation.
    fd = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _propagation_state(snapshot, attempt):
    if 'versionPropagation' not in attempt:
        return None  # Legacy attempts retain strict live-head matching.
    state = attempt['versionPropagation']
    receipt = Path(snapshot) / 'hosting-deploy-result.json'
    contract.require(type(state) is dict and set(state) == {
        'schemaVersion', 'attemptId', 'baselineVersion', 'ownedVersion',
        'cliReceiptSha256', 'ownedVersionObserved'}
        and state['schemaVersion'] == PROPAGATION_STATE_SCHEMA
        and state['attemptId'] == attempt['attemptId']
        and state['baselineVersion'] == attempt['baselineVersion']
        and state['ownedVersion'] == attempt['newVersion']
        and type(state['ownedVersionObserved']) is bool,
        'Invalid persisted Hosting propagation state')
    contract.require(hashlib.sha256(receipt.read_bytes()).hexdigest() == state['cliReceiptSha256']
        and deployed_version(receipt, site=attempt['intent']['site'],
                             baseline_version=attempt['baselineVersion']) == state['ownedVersion'],
        'Propagation state differs from CLI deployment receipt')
    return state


def _observe_owned_version(request, attempt, path, state):
    version = live_version(request, attempt['intent']['site'])
    if state is not None and version == attempt['baselineVersion'] and not state['ownedVersionObserved']:
        raise ValueError('Deployed Hosting version has not propagated')
    if version != attempt['newVersion']:
        raise PublicationVersionChanged('Live Hosting version differs from deployment receipt')
    if state is not None and not state['ownedVersionObserved']:
        state['ownedVersionObserved'] = True
        _persist_attempt(path, attempt)
    return version


def publish(snapshot, *, intent, routes, baseline_version, baseline_catalog_sha,
            lease_bucket, request, reader, run=subprocess.run, heartbeat_interval=5,
            baseline_catalog_v4_sha=None):
    """``baseline_catalog_v4_sha`` is the live v4 catalog the snapshot was built on (None: none yet)."""
    contract.require(heartbeat_interval > 0, 'Heartbeat interval must be positive')
    with publisher_lock(snapshot):
        return _publish(snapshot, intent=intent, routes=routes, baseline_version=baseline_version,
                        baseline_catalog_sha=baseline_catalog_sha, lease_bucket=lease_bucket,
                        request=request, reader=reader, run=run, heartbeat_interval=heartbeat_interval,
                        baseline_catalog_v4_sha=baseline_catalog_v4_sha)


def _publish(snapshot, *, intent, routes, baseline_version, baseline_catalog_sha,
             lease_bucket, request, reader, run, heartbeat_interval, baseline_catalog_v4_sha):
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
        contract.require(public_catalog_v4(reader, intent['origin']) == baseline_catalog_v4_sha, 'Live v4 catalog changed; rebuild against current snapshot')
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
        result_path = snapshot / 'hosting-deploy-result.json'
        with progress.heartbeat(heartbeat_interval), (snapshot / 'hosting-publish.log').open('w') as log, result_path.open('w') as output:
            run(['firebase', 'deploy', '--only', 'hosting', '--project', intent['project'], '--config', str(bound_config.resolve()), '--non-interactive', '--json'],
                cwd=snapshot, check=True, stdout=output, stderr=log, timeout=3600)
        attempt['newVersion'] = deployed_version(result_path, site=intent['site'], baseline_version=baseline_version)
        attempt['versionPropagation'] = {
            'schemaVersion': PROPAGATION_STATE_SCHEMA, 'attemptId': attempt['attemptId'],
            'baselineVersion': baseline_version, 'ownedVersion': attempt['newVersion'],
            'cliReceiptSha256': hashlib.sha256(result_path.read_bytes()).hexdigest(),
            'ownedVersionObserved': False}
        _persist_attempt(receipt_path, attempt)
        progress.update('verifying_readback')
        lease.check()

        state = _propagation_state(snapshot, attempt)

        def readback():
            version = _observe_owned_version(request, attempt, receipt_path, state)
            contract.require(public_catalog(reader, intent['origin']) == attempt['catalogSha256'], 'Published catalog readback differs')
            contract.require(public_catalog_v4(reader, intent['origin']) == report.get('catalogV4Sha256'), 'Published v4 catalog readback differs')
            if live_version(request, intent['site']) != attempt['newVersion']:
                raise PublicationVersionChanged('Live Hosting version changed during catalog readback')
            return version
        version = await_propagation(readback)
        attempt.update(newVersion=version, completedAt=datetime.now(timezone.utc).isoformat(), status='deployed')
        _persist_attempt(receipt_path, attempt)
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
    contract.require((attempt.get('newVersion') or confirmed_version) == confirmed_version,
                     'Confirmed version differs from recorded deployment version (first observed for legacy attempts)')
    state = _propagation_state(snapshot, attempt)
    if state is None:
        # No historical durable observation flag exists: never infer false.
        observed = live_version(request, attempt['intent']['site'])
        contract.require(observed == confirmed_version and observed != attempt['baselineVersion'],
                         'Explicit confirmed new version differs')
    else:
        observed = confirmed_version
    report = json.loads((Path(snapshot) / 'seal-report.json').read_text())

    def catalogs():
        if state is None:
            if live_version(request, attempt['intent']['site']) != confirmed_version:
                raise PublicationVersionChanged('Live Hosting version changed during reconciliation')
        else:
            _observe_owned_version(request, attempt, path, state)
        contract.require(public_catalog(reader, attempt['intent']['origin']) == attempt['catalogSha256'], 'Remote catalog differs; manual recovery required')
        contract.require(public_catalog_v4(reader, attempt['intent']['origin']) == report.get('catalogV4Sha256'),
                         'Remote v4 catalog differs; manual recovery required')
        if live_version(request, attempt['intent']['site']) != confirmed_version:
            raise PublicationVersionChanged('Live Hosting version changed during reconciliation')
    await_propagation(catalogs)
    attempt.update(status='deployed', newVersion=observed, completedAt=datetime.now(timezone.utc).isoformat())
    _persist_attempt(path, attempt)
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
    def reader(url, *, timeout=60):
        with urllib.request.urlopen(urllib.request.Request(url, headers={'Cache-Control': 'no-cache'}), timeout=timeout) as response:
            return response.status, response.read()
    result = publish(**config, request=authenticated_transport(), reader=reader)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
