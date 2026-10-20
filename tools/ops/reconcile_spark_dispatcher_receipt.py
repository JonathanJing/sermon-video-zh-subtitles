#!/usr/bin/env python3
"""One-time, receipt-bound reconciliation for a proven pre-dispatch CLI error.

This deliberately does not provide a boolean release path. It only closes an
unbound Mac dispatcher hold when immutable evidence identifies the session,
owner, exact dispatcher, and a Python argument-binding failure before the
callable body or Codex CLI could run.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

SCHEMA = 'spark-dispatcher-precall-error-receipt-v1'
ALLOWED_ERROR = "call_json() got an unexpected keyword argument 'resource_class'"
ALLOWED_ERRORS = {ALLOWED_ERROR, ALLOWED_ERROR + ". Did you mean 'resource_policy'?"}


class ReceiptError(RuntimeError):
    pass


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_receipt(receipt):
    required = {
        'schemaVersion': SCHEMA,
        'failurePhase': 'python_argument_binding_before_callable_body',
        'errorType': 'TypeError',
        'callableBodyEntered': False,
        'codexCliSpawned': False,
        'modelCallCount': 0,
        'dispatcherExited': True,
    }
    if (not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in required.items())
            or receipt.get('errorMessage') not in ALLOWED_ERRORS):
        raise ReceiptError('precall_error_receipt_not_eligible')
    for name in ('sessionId', 'owner', 'jobId', 'dispatcherHost'):
        if not isinstance(receipt.get(name), str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}', receipt[name]):
            raise ReceiptError('precall_error_receipt_identity_invalid')
    if type(receipt.get('dispatcherPid')) is not int or receipt['dispatcherPid'] <= 1:
        raise ReceiptError('precall_error_receipt_dispatcher_invalid')
    evidence = receipt.get('evidenceSha256')
    if (not isinstance(evidence, dict) or set(evidence) != {'runLog', 'modelCallLedger', 'exitProbe', 'signatureProbe'}
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                   for value in evidence.values())):
        raise ReceiptError('precall_error_receipt_evidence_invalid')
    for name in ('oldControllerSha256', 'newControllerSha256'):
        if not isinstance(receipt.get(name), str) or not re.fullmatch(r'[0-9a-f]{64}', receipt[name]):
            raise ReceiptError('precall_error_receipt_controller_invalid')
    return receipt


def reconcile(state_dir, receipt, *, expected_controller_sha256):
    receipt = validate_receipt(receipt)
    if receipt['newControllerSha256'] != expected_controller_sha256:
        raise ReceiptError('precall_error_receipt_new_controller_mismatch')
    state_dir = Path(state_dir)
    state_path = state_dir / 'session.json'
    lock_fd = os.open(state_dir / 'owner.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text())
        if (state.get('sessionId') != receipt['sessionId'] or state.get('owner') != receipt['owner']
                or state.get('controllerSha256') != receipt['oldControllerSha256']
                or state.get('status') != 'reconcile_required'):
            raise ReceiptError('precall_error_receipt_session_binding_mismatch')
        job = state.get('jobs', {}).get(receipt['jobId'])
        if (not job or job.get('status') != 'unknown' or job.get('sessionId') != receipt['sessionId']
                or job.get('owner') != receipt['owner'] or job.get('processes') or job.get('containerIds')
                or job.get('dispatcher') != {'host': receipt['dispatcherHost'], 'pid': receipt['dispatcherPid']}
                or job.get('purpose') != 'production-model-call'):
            raise ReceiptError('precall_error_receipt_job_binding_mismatch')
        unknown = [row for row in state.get('jobs', {}).values() if row.get('status') == 'unknown']
        if len(unknown) != 1 or unknown[0]['jobId'] != receipt['jobId']:
            raise ReceiptError('precall_error_receipt_multiple_unknown_jobs')
        timestamp = datetime.now(timezone.utc).isoformat()
        job.update(status='terminal', endedAt=timestamp, terminalEvidence={
            'kind': 'dispatcher_pre_call_error_receipt',
            'receiptSha256': _sha(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()),
            'evidenceSha256': receipt['evidenceSha256'],
        })
        state['status'] = 'exclusive_ready'
        state['controllerSha256'] = expected_controller_sha256
        state['revision'] += 1
        state['updatedAt'] = timestamp
        state.setdefault('events', []).append({
            'revision': state['revision'], 'at': timestamp,
            'event': 'unbound_dispatcher_terminal_receipt_reconciled',
            'jobId': receipt['jobId'],
            'receiptSha256': job['terminalEvidence']['receiptSha256'],
            'controllerSha256': expected_controller_sha256,
        })
        _atomic_json(state_path, state)
        return state
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', default=str(Path.home() / '.local/state/tongxing-spark-exclusive'))
    parser.add_argument('--controller-sha256', required=True)
    args = parser.parse_args()
    try:
        receipt = json.load(sys.stdin)
        state = reconcile(args.state_dir, receipt, expected_controller_sha256=args.controller_sha256)
        print(json.dumps({'status': state['status'], 'revision': state['revision'],
                          'jobId': receipt['jobId'], 'controllerSha256': state['controllerSha256']}, sort_keys=True))
        return 0
    except (OSError, ValueError, ReceiptError) as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, ReceiptError) else type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
