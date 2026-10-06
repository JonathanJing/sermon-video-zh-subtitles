import hashlib
import json

import pytest

from scripts import reconcile_spark_dispatcher_receipt as recovery


def fixture(tmp_path):
    root = tmp_path / 'state'
    root.mkdir()
    state = {
        'schemaVersion': 'tongxing-spark-exclusive-v1',
        'sessionId': 'run-605s-pr248-20261005', 'owner': 'codex-pr248',
        'status': 'reconcile_required', 'revision': 14, 'updatedAt': 'before',
        'controllerSha256': 'a' * 64, 'events': [],
        'jobs': {'job-123': {
            'jobId': 'job-123', 'sessionId': 'run-605s-pr248-20261005', 'owner': 'codex-pr248',
            'purpose': 'production-model-call', 'status': 'unknown', 'processes': [], 'containerIds': [],
            'dispatcher': {'host': 'MacBookPro.localdomain', 'pid': 60927},
        }},
    }
    (root / 'session.json').write_text(json.dumps(state))
    receipt = {
        'schemaVersion': recovery.SCHEMA, 'failurePhase': 'python_argument_binding_before_callable_body',
        'errorType': 'TypeError', 'errorMessage': recovery.ALLOWED_ERROR,
        'callableBodyEntered': False, 'codexCliSpawned': False, 'modelCallCount': 0,
        'dispatcherExited': True, 'sessionId': state['sessionId'], 'owner': state['owner'],
        'jobId': 'job-123', 'dispatcherHost': 'MacBookPro.localdomain', 'dispatcherPid': 60927,
        'oldControllerSha256': 'a' * 64, 'newControllerSha256': 'b' * 64,
        'evidenceSha256': {key: str(i) * 64 for i, key in enumerate(
            ('runLog', 'modelCallLedger', 'exitProbe', 'signatureProbe'), 1)},
    }
    return root, state, receipt


def test_receipt_reconciles_only_exact_single_unknown_job(tmp_path):
    root, before, receipt = fixture(tmp_path)
    state = recovery.reconcile(root, receipt, expected_controller_sha256='b' * 64)
    assert state['status'] == 'exclusive_ready'
    assert state['revision'] == before['revision'] + 1
    job = state['jobs']['job-123']
    assert job['status'] == 'terminal'
    assert job['terminalEvidence']['kind'] == 'dispatcher_pre_call_error_receipt'
    assert state['events'][-1]['event'] == 'unbound_dispatcher_terminal_receipt_reconciled'


@pytest.mark.parametrize('change', [
    {'callableBodyEntered': True}, {'codexCliSpawned': True}, {'modelCallCount': 1},
    {'dispatcherExited': False}, {'errorMessage': 'arbitrary error'},
    {'dispatcherPid': 42}, {'newControllerSha256': 'c' * 64},
])
def test_receipt_rejects_unsafe_or_mismatched_claims(tmp_path, change):
    root, _, receipt = fixture(tmp_path)
    receipt.update(change)
    with pytest.raises(recovery.ReceiptError):
        recovery.reconcile(root, receipt, expected_controller_sha256='b' * 64)


def test_receipt_rejects_multiple_unknown_holds(tmp_path):
    root, _, receipt = fixture(tmp_path)
    state_path = root / 'session.json'
    state = json.loads(state_path.read_text())
    state['jobs']['other'] = {'jobId': 'other', 'status': 'unknown'}
    state_path.write_text(json.dumps(state))
    with pytest.raises(recovery.ReceiptError, match='multiple_unknown'):
        recovery.reconcile(root, receipt, expected_controller_sha256='b' * 64)
