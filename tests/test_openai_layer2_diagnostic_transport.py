import json

import pytest

from scripts.openai_layer2_diagnostic_transport import OpenAILayer2DiagnosticTransport, _digest


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
