import io
import json
import threading
from types import SimpleNamespace

import pytest

from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import capture_supervisor_model_usage as capture
from scripts import serve_milmmt_v41_local as local


def ledger(directory):
    return [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]


def test_codex_live_turn_usage_with_tool_wait_is_session_rate_only(tmp_path):
    stream = [json.dumps(row) for row in (
        {'type': 'turn.started'}, {'type': 'item.completed', 'item': {'text': 'secret prompt and output'}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 90, 'output_tokens': 10}},
        {'type': 'turn.started'}, {'type': 'turn.completed', 'usage': {'input_tokens': 120, 'output_tokens': 20}})]
    with accounting.accounting_session(tmp_path, 'capture_test'):
        result = capture.capture_codex(stream, 'gpt-6-luna')
    assert result['completedTurns'] == 2
    assert 'secret' not in (tmp_path / 'events.jsonl').read_text()
    calls = accounting.summarize(tmp_path)['modelCallReport']['calls']
    assert len(calls) == 2
    assert sum(call['usage']['outputTokens'] for call in calls) == 30
    assert all(call['role'] == 'supervisor' and call['generationTokensPerSecond'] is None
               and call['effectiveRequestTokensPerSecond'] is None for call in calls)
    assert all(call['sessionOutputTokensPerSecond'] is not None for call in calls)
    assert (tmp_path / 'model-calls.csv').exists()


def test_interrupted_codex_turn_retains_failed_attempt_and_unknown_usage(tmp_path):
    with accounting.accounting_session(tmp_path, 'capture_test'):
        with pytest.raises(InterruptedError):
            capture.capture_codex(['{"type":"turn.started"}'], 'gpt-6-luna')
    call = accounting.summarize(tmp_path)['modelCallReport']['calls'][0]
    assert call['status'] == 'failed'
    assert call['usage']['outputTokens'] is None
    assert call['sessionOutputTokensPerSecond'] is None


def test_codex_fast_credits_reach_json_csv_without_polluting_api_cost(tmp_path):
    with profile.context(workKind='control', evidenceMode='synthetic', executorType='decision_agent'):
        with accounting.accounting_session(tmp_path, 'credit_capture'):
            capture.capture_codex(['{"type":"turn.started"}',
                '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":90,"output_tokens":10}}'],
                'gpt-6-luna', service_tier='fast')
    summary = accounting.summarize(tmp_path)
    assert not summary['ledgerIntegrity']['damagedEvents']
    call = summary['modelCallReport']['calls'][0]
    assert call['creditUsage']['estimatedCredits'] == 0.000345
    assert summary['modelCallReport']['creditUsage']['estimatedCreditsKnownSubtotal'] == 0.000345
    assert call['creditUsage']['actualCredits'] is None
    assert 'creditUsage' in (tmp_path/'model-calls.csv').read_text()
    assert all(run['apiAttempts'] == 0 and run['knownEstimatedUsd'] == 0 for run in summary['runs'])


def test_capture_rejects_finish_without_observed_start(tmp_path):
    with accounting.accounting_session(tmp_path, 'capture_test'):
        with pytest.raises(ValueError, match='start_not_observed'):
            capture.capture_codex(['{"type":"turn.completed","usage":{"output_tokens":100}}'], 'gpt-6-luna')
    assert not accounting.summarize(tmp_path)['modelCallReport']['calls']


def test_codex_failed_event_is_not_reported_as_success(tmp_path):
    with accounting.accounting_session(tmp_path, 'capture_test'):
        result = capture.capture_codex(['{"type":"turn.started"}',
            '{"type":"turn.failed","error":{"message":"private failure"}}'], 'gpt-6-luna')
    assert result['status'] == 'needs_attention' and result['failedTurns'] == 1
    assert result['completedTurns'] == 0
    assert 'private failure' not in (tmp_path / 'events.jsonl').read_text()


def test_model_import_uses_original_timing_and_deduplicates_repeated_calls(tmp_path):
    with accounting.accounting_session(tmp_path / 'original', 'capture_test'):
        capture.capture_codex(['{"type":"turn.started"}',
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}'], 'gpt-6-luna')
    fields = [row['fields'] for row in ledger(tmp_path / 'original') if row.get('code') == 'model_call_observation']
    target = tmp_path / 'imported'
    with accounting.accounting_session(target, 'import_test'):
        for _ in range(2):
            capture.import_observations([json.dumps(field) for field in fields])
    report = accounting.summarize(target)['modelCallReport']
    assert len(report['calls']) == 1
    assert report['calls'][0]['elapsedSeconds'] == fields[-1]['elapsedSeconds']
    assert report['equivalentDuplicatesIgnored'] == 2


def test_model_observation_roundtrips_canonical_profile(tmp_path):
    with profile.context(workKind='control', evidenceMode='synthetic', executorType='decision_agent'):
        with accounting.accounting_session(tmp_path, 'profile_capture'):
            capture.capture_codex(['{"type":"turn.started"}', '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}'], 'gpt-6-luna')
    rows = ledger(tmp_path)
    assert all(accounting._valid_event(row) for row in rows)
    summary = accounting.summarize(tmp_path)
    assert not summary['ledgerIntegrity']['damagedEvents']
    assert summary['modelCallReport']['calls'][0]['usage']['outputTokens'] == 2


def test_local_mlx_records_actual_tokens_without_copying_text(tmp_path):
    engine = local.MLXEngine.__new__(local.MLXEngine)
    engine.tokenizer = SimpleNamespace(encode=lambda *args, **kwargs: [1, 2, 3])
    engine.model = object(); engine.sampler = object()
    engine.mx = SimpleNamespace(random=SimpleNamespace(seed=lambda value: None), synchronize=lambda: None)
    def responses(*args, **kwargs):
        yield SimpleNamespace(text='秘密', token=10, finish_reason=None, generation_tokens=1)
        yield SimpleNamespace(text='文字', token=11, finish_reason='stop', generation_tokens=2, generation_tps=20)
    engine.stream_generate = responses
    with accounting.accounting_session(tmp_path, 'local_test'):
        result = engine.translate('private source', lambda event: None, threading.Event())
    assert result['text'] == '秘密文字'
    assert 'private source' not in (tmp_path / 'events.jsonl').read_text()
    assert '秘密' not in (tmp_path / 'events.jsonl').read_text()
    call = accounting.summarize(tmp_path)['modelCallReport']['calls'][0]
    assert call['backend'] == 'local'
    assert call['usage']['inputTokens'] == 3 and call['usage']['outputTokens'] == 2
    assert call['generationTokensPerSecond'] == 20
    assert call['firstTokenSeconds'] is not None


def test_local_mlx_cancel_retains_partial_real_counts(tmp_path):
    engine = local.MLXEngine.__new__(local.MLXEngine)
    engine.tokenizer = SimpleNamespace(encode=lambda *args, **kwargs: [1, 2, 3])
    engine.model = object(); engine.sampler = object()
    engine.mx = SimpleNamespace(random=SimpleNamespace(seed=lambda value: None), synchronize=lambda: None)
    cancelled = threading.Event()
    def responses(*args, **kwargs):
        yield SimpleNamespace(text='片段', token=10, finish_reason=None, generation_tokens=1)
        cancelled.set()
        yield SimpleNamespace(text='ignored', token=11, finish_reason='stop', generation_tokens=2)
    engine.stream_generate = responses
    with accounting.accounting_session(tmp_path, 'local_test'):
        with pytest.raises(local.RequestError):
            engine.translate('private', lambda event: None, cancelled)
    call = accounting.summarize(tmp_path)['modelCallReport']['calls'][0]
    assert call['status'] == 'failed' and call['usage']['outputTokens'] == 1
    assert call['generationTokensPerSecond'] is None


def test_service_default_session_attributes_worker_calls(tmp_path, monkeypatch):
    from scripts import sermon_model_call_observation as observations
    def fake_service(args):
        def worker():
            with observations.invocation('test-local', backend='local', provider='mlx', role='production',
                                        usage_source='local_tokenizer') as receipt:
                receipt['usage'] = {'inputTokens': 3, 'outputTokens': 2}
        thread = threading.Thread(target=worker)
        thread.start(); thread.join()
    monkeypatch.setattr(local, '_serve', fake_service)
    local.serve(SimpleNamespace(state_dir=tmp_path))
    report = accounting.summarize(tmp_path / 'accounting')['modelCallReport']
    assert len(report['calls']) == 1
    assert report['calls'][0]['backend'] == 'local'
    assert report['calls'][0]['usage']['outputTokens'] == 2
