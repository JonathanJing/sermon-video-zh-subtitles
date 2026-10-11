import json

import pytest

from scripts.openai_layer2_diagnostic_transport import OpenAILayer2DiagnosticTransport, _digest
from scripts import sermon_provider_limits


def test_reuse_requires_exact_completed_prior_receipt(tmp_path, monkeypatch):
    transport = object.__new__(OpenAILayer2DiagnosticTransport)
    transport.reuse_receipts_dir = tmp_path
    transport.execution_identity = {'projectId': 'proj_test', 'backend': 'openai_api'}
    payload = {'model': 'gpt-6.1-sol', 'messages': []}
    fingerprint = _digest({'payload': payload, 'executionIdentity': transport.execution_identity})
    source = tmp_path / fingerprint
    source.mkdir()
    response = {'id': 'call-1', 'model': 'gpt-6.1-sol', 'choices': [{'finish_reason': 'stop',
        'message': {'content': '{}'}}]}
    (source / 'started.json').write_text(json.dumps({'payloadSha256': _digest(payload),
        'executionIdentity': transport.execution_identity}))
    (source / 'response.json').write_text(json.dumps({'payloadSha256': _digest(payload),
        'response': response}))
    monkeypatch.setattr('scripts.openai_layer2_diagnostic_transport.models.completed_response_content',
                        lambda result, model, role: '{}')
    assert transport._reused_response(fingerprint, payload) == response
    (source / 'response.json').unlink()
    with pytest.raises(RuntimeError, match='not_reconciled'):
        transport._reused_response(fingerprint, payload)


def _budget_transport(tmp_path, *, max_requests, hard_limit):
    transport = object.__new__(OpenAILayer2DiagnosticTransport)
    transport.budget_lock_path = tmp_path / '.budget-ledger.lock'
    transport.budget_ledger_path = tmp_path / 'budget-ledger.json'
    transport.budget_config = {'maxRequests': max_requests, 'hardLimitMicrousd': hard_limit}
    transport._budget_identity = 'bound-test-budget'
    return transport


def test_budget_ledger_reserves_before_calls_and_enforces_request_cap(tmp_path):
    limits = sermon_provider_limits.DEFAULT_REQUEST_LIMITS
    request = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
        'messages': [{'role': 'user', 'content': 'synthetic input'}],
        'response_format': {'type': 'json_object'}}
    bound = sermon_provider_limits.request_bounds(request, limits)
    transport = _budget_transport(tmp_path, max_requests=1, hard_limit=bound['costMicrousd'])
    transport._reserve_budget('first', request, bound)
    ledger = json.loads(transport.budget_ledger_path.read_text())
    assert ledger['reservations']['first']['status'] == 'reserved'
    assert ledger['reservations']['first']['reservedMicrousd'] == bound['costMicrousd']
    with pytest.raises(RuntimeError, match='request_cap'):
        transport._reserve_budget('second', request, bound)


def test_budget_ledger_rejects_hard_cap_overrun_without_mutation(tmp_path):
    limits = sermon_provider_limits.DEFAULT_REQUEST_LIMITS
    request = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
        'messages': [{'role': 'user', 'content': 'synthetic input'}],
        'response_format': {'type': 'json_object'}}
    bound = sermon_provider_limits.request_bounds(request, limits)
    transport = _budget_transport(tmp_path, max_requests=2, hard_limit=bound['costMicrousd'] - 1)
    with pytest.raises(RuntimeError, match='hard_cap'):
        transport._reserve_budget('first', request, bound)
    assert not transport.budget_ledger_path.exists()
