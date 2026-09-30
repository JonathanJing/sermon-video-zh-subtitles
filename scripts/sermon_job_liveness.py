"""Bounded local job liveness; heartbeat is not completed work or retry authority.

The existing durable job owner observes monotonically advancing local receipts.
Only the trusted command reports meaningful checkpoints. Wall clocks and mtime
never extend deadlines; expired/invalid evidence requires reconciliation.
"""
from __future__ import annotations

from contextlib import contextmanager
import math
import re
import threading
import time

SCHEMA = 'sermon-job-liveness-v1'
FILE = 'liveness.json'
MAX_BYTES = 16384
POLICY_KEYS = {'schemaVersion', 'startTimeoutSeconds', 'heartbeatIntervalSeconds',
               'heartbeatTimeoutSeconds', 'noProgressTimeoutSeconds'}


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS or policy['schemaVersion'] != SCHEMA:
        raise ValueError('invalid_liveness_policy')
    for key in POLICY_KEYS - {'schemaVersion'}:
        value = policy[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 21600:
            raise ValueError('invalid_liveness_timeout')
    if not policy['heartbeatIntervalSeconds'] < policy['heartbeatTimeoutSeconds'] <= policy['noProgressTimeoutSeconds']:
        raise ValueError('invalid_liveness_timeout_order')
    return dict(policy)


def valid_policy(policy):
    try:
        validate_policy(policy)
        return True
    except (TypeError, ValueError, KeyError):
        return False


class LivenessError(RuntimeError):
    pass


class Reporter:
    def __init__(self, folder, request):
        from scripts import sermon_workflow_jobs as jobs
        self.folder, self.jobs = folder, jobs
        self.policy = validate_policy(request['livenessPolicy'])
        self.value = {'schemaVersion': SCHEMA, 'jobId': request['jobId'],
                      'requestSha256': jobs._digest(request), 'sequence': 0,
                      'progressSequence': 0, 'stage': 'startup', 'phase': 'running'}
        self.mutex, self.stop = threading.Lock(), threading.Event()
        self.error = None
        self.thread = None

    def _write(self):
        self.value['sequence'] += 1
        self.jobs._persist(self.folder / FILE, self.value)

    def check(self):
        if self.error is not None:
            raise LivenessError('liveness_receipt_write_failed') from self.error

    def progress(self, stage):
        if not isinstance(stage, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', stage):
            raise ValueError('invalid_liveness_stage')
        with self.mutex:
            self.check()
            self.value['stage'] = stage
            self.value['progressSequence'] += 1
            self._write()

    def start(self):
        self.progress('admitted')  # Durable before the command's first side effect.
        def pulse():
            while not self.stop.wait(self.policy['heartbeatIntervalSeconds']):
                try:
                    with self.mutex:
                        self._write()  # Deliberately does not advance progress.
                except BaseException as exc:
                    self.error = exc
                    self.stop.set()
        self.thread = threading.Thread(target=pulse, daemon=True, name='job-liveness-reporter')
        self.thread.start()
        return self

    def close(self, *, completed):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise LivenessError('liveness_reporter_did_not_stop')
        self.check()
        if completed:
            with self.mutex:
                self.value['phase'] = 'finished'
                self.value['stage'] = 'command_finished'
                self.value['progressSequence'] += 1
                self._write()


@contextmanager
def report(folder, request):
    reporter = Reporter(folder, request).start()
    try:
        yield reporter
    except BaseException:
        reporter.close(completed=False)
        raise
    else:
        reporter.close(completed=True)


class Monitor:
    def __init__(self, folder, request, *, clock=time.monotonic):
        from scripts import sermon_workflow_jobs as jobs
        self.folder, self.request, self.jobs = folder, request, jobs
        self.policy = validate_policy(request['livenessPolicy'])
        self.clock = clock
        self.started = self.last_heartbeat = self.last_progress = clock()
        self.sequence = self.progress_sequence = 0
        self.last = None
        self.reason = None
        self.cancel, self.stop = threading.Event(), threading.Event()
        self.thread = None

    def _fail(self, reason):
        self.reason = reason
        self.cancel.set()

    def poll(self):
        if self.reason:
            return
        now = self.clock()
        try:
            path = self.folder / FILE
            try:
                # _read also refuses links/non-regular files; bound parse size.
                self.jobs._reject_link(path, directory=False)
                if path.stat().st_size > MAX_BYTES:
                    raise ValueError('oversized_liveness_receipt')
                value = self.jobs._read(path)
            except FileNotFoundError:
                value = None
            if value is not None:
                if (not isinstance(value, dict) or set(value) != {'schemaVersion', 'jobId', 'requestSha256',
                        'sequence', 'progressSequence', 'stage', 'phase'}
                        or value['schemaVersion'] != SCHEMA or value['jobId'] != self.request['jobId']
                        or value['requestSha256'] != self.jobs._digest(self.request)
                        or type(value['sequence']) is not int or type(value['progressSequence']) is not int
                        or not 1 <= value['progressSequence'] <= value['sequence'] <= 2**53
                        or value['sequence'] < self.sequence or value['progressSequence'] < self.progress_sequence
                        or value['phase'] not in {'running', 'finished'}
                        or not isinstance(value['stage'], str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value['stage'])
                        or (value['sequence'] == self.sequence and value != self.last)):
                    raise ValueError('invalid_liveness_receipt')
                if value['sequence'] > self.sequence:
                    self.sequence, self.last_heartbeat = value['sequence'], now
                if value['progressSequence'] > self.progress_sequence:
                    self.progress_sequence, self.last_progress = value['progressSequence'], now
                self.last = value
            if not self.sequence and now - self.started >= self.policy['startTimeoutSeconds']:
                self._fail('liveness_start_timeout')
            elif self.sequence and now - self.last_heartbeat >= self.policy['heartbeatTimeoutSeconds']:
                self._fail('liveness_heartbeat_timeout')
            elif self.sequence and now - self.last_progress >= self.policy['noProgressTimeoutSeconds']:
                self._fail('liveness_no_progress_timeout')
        except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
            self._fail('liveness_invalid_receipt')

    def start(self):
        def watch():
            interval = min(.25, self.policy['heartbeatIntervalSeconds'] / 2)
            while not self.stop.is_set():
                self.poll()
                if self.cancel.is_set() or self.stop.wait(interval):
                    break
        self.thread = threading.Thread(target=watch, daemon=True, name='job-liveness-monitor')
        self.thread.start()
        return self

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                self._fail('liveness_monitor_did_not_stop')

    def completed(self):
        self.close()
        self.poll()
        if self.reason is None and (self.last is None or self.last['phase'] != 'finished'):
            self._fail('liveness_completion_receipt_missing')
        return self.reason is None
