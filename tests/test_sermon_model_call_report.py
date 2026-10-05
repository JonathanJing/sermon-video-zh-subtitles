import copy
import unittest

from scripts.sermon_model_call_report import report


def event(kind, ident='a', run='r', **extra):
    return dict(event=kind, eventId=kind + ident, runId=run, spanId='s',
                recordedAt='2026-10-05T00:00:00Z', **extra)


def api(output=100, elapsed=2, ident='a', run='r', **extra):
    return event('api_attempt', ident, run, attemptId=ident, model='model-1',
                 requestedModel='model-alias', status='completed',
                 elapsedSeconds=elapsed, usage={'inputTokens': 20, 'outputTokens': output}, **extra)


def generic(phase='finished', **overrides):
    fields = dict(callId='a', phase=phase, model='model-1', backend='local', provider='ollama',
                  role='production', timingScope='request', status='completed' if phase == 'finished' else 'started',
                  usage={'outputTokens': 100}, elapsedSeconds=2 if phase == 'finished' else None,
                  generationSeconds=1 if phase == 'finished' else None,
                  startedAt='2026-10-05T00:00:00Z', finishedAt='2026-10-05T00:00:02Z' if phase == 'finished' else None)
    fields.update(overrides)
    return event('log', phase, code='model_call_observation', fields=fields)


def local(status, ident):
    return event('log', ident, code='local_model_observation', fields=dict(model='qwen-tts', status=status,
        elapsedSeconds=2 if status != 'started' else None, providerTokens=None))


class ModelCallReportTests(unittest.TestCase):
    def test_api_requested_actual_timing_and_unknown_provider(self):
        start = event('api_attempt_started', attemptId='a', model='model-alias')
        row = report([start, api()])['calls'][0]
        self.assertEqual(row['requestedModel'], 'model-alias')
        self.assertEqual(row['model'], 'model-1')
        self.assertEqual(row['provider'], 'not_recorded')
        self.assertEqual(row['effectiveRequestTokensPerSecond'], 50)
        self.assertIsNone(row['generationTokensPerSecond'])
        self.assertEqual(row['startedAt'], start['recordedAt'])

    def test_provider_only_from_evidence_and_role_stage(self):
        stage = event('stage_started', executorType='decision_agent')
        row = report([stage, api(provider='openai')])['calls'][0]
        self.assertEqual(row['role'], 'supervisor')
        self.assertEqual(row['provider'], 'openai')

    def test_sdk_session_is_not_generation(self):
        start = event('sdk_call_started', invocationId='i', model='codex-luna', agentBackend='codex')
        end = event('sdk_call_finished', invocationId='i', model='codex-luna', agentBackend='codex',
                    status='completed', elapsedSeconds=10, usage={'output_tokens': 100})
        row = report([start, end])['calls'][0]
        self.assertEqual(row['sessionOutputTokensPerSecond'], 10)
        self.assertIsNone(row['effectiveRequestTokensPerSecond'])
        self.assertIsNone(row['generationTokensPerSecond'])
        self.assertEqual(row['role'], 'supervisor')
        self.assertEqual(row['backend'], 'agent_session')
        self.assertEqual(row['agentBackend'], 'codex')

    def test_generic_reported_usage_does_not_require_absent_cache_write_field(self):
        row = report([generic(usage={k: 1 for k in ('inputTokens', 'outputTokens', 'totalTokens', 'cachedInputTokens', 'reasoningTokens')})])['calls'][0]
        self.assertEqual(row['usageStatus'], 'reported')
        self.assertIsNone(row['usage']['cacheWriteTokens'])

    def test_local_v1_pairs_but_has_no_tokens(self):
        result = report([local('started', '1'), local('completed', '2')])
        row = result['calls'][0]
        self.assertEqual(row['pairingStatus'], 'paired')
        self.assertEqual(row['elapsedSeconds'], 2)
        self.assertEqual(row['usageStatus'], 'not_reported')
        self.assertIsNone(row['effectiveRequestTokensPerSecond'])
        self.assertEqual(row['backend'], 'local')

    def test_ambiguous_local_calls_do_not_join(self):
        result = report([local('started', '1'), local('started', '2'), local('completed', '3')])
        self.assertEqual(len(result['calls']), 3)
        self.assertTrue(all(r['pairingStatus'] == 'individual_observation' for r in result['calls']))

    def test_generic_measured_generation_and_explicit_timestamps(self):
        row = report([generic('started', usage={}), generic()])['calls'][0]
        self.assertEqual(row['generationTokensPerSecond'], 100)
        self.assertEqual(row['effectiveRequestTokensPerSecond'], 50)
        self.assertEqual(row['finishedAt'], '2026-10-05T00:00:02Z')

    def test_generic_session_only_session_rate(self):
        row = report([generic(backend='agent_session', role='supervisor',
                              timingScope='agent_session_including_tools', generationSeconds=None)])['calls'][0]
        self.assertEqual(row['sessionOutputTokensPerSecond'], 50)
        self.assertIsNone(row['generationTokensPerSecond'])
        self.assertIsNone(row['effectiveRequestTokensPerSecond'])

    def test_open_api_and_generic_calls(self):
        result = report([event('api_attempt_started', attemptId='x', model='m'), generic('started', usage={})])
        self.assertEqual(len(result['calls']), 2)
        self.assertTrue(all(r['elapsedSeconds'] is None for r in result['calls']))
        self.assertTrue(all(r['usage']['outputTokens'] is None for r in result['calls']))

    def test_identical_duplicate_no_double_count(self):
        row = api(); duplicate = {**row, 'eventId': 'imported', 'recordedAt': '2026-10-05T01:00:00Z'}
        result = report([row, duplicate])
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['equivalentDuplicatesIgnored'], 1)
        self.assertEqual(result['totals'][0]['usage']['outputTokens']['knownSubtotal'], 100)

    def test_conflicting_duplicate_suppresses_tokens(self):
        result = report([api(), api(output=200)])
        row = result['calls'][0]
        self.assertEqual(row['status'], 'conflict')
        self.assertIsNone(row['usage']['outputTokens'])
        self.assertIsNone(row['effectiveRequestTokensPerSecond'])

    def test_cross_run_same_provider_response_deduplicates(self):
        result = report([api(responseId='resp'), api(run='other', responseId='resp')])
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['equivalentDuplicatesIgnored'], 1)

    def test_distinct_provider_accounts_do_not_deduplicate_same_response_id(self):
        result = report([api(responseId='resp', providerScopeKey='account1'),
                         api(run='other', responseId='resp', providerScopeKey='account2')])
        self.assertEqual(len(result['calls']), 2)

    def test_cross_run_response_conflict(self):
        result = report([api(responseId='resp'), api(run='other', output=200, responseId='resp')])
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['calls'][0]['status'], 'conflict')

    def test_correlated_generic_and_api_count_once(self):
        result = report([api(), generic(backend='api', provider='openai')])
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['calls'][0]['generationTokensPerSecond'], 100)

    def test_correlated_conflicting_generic_and_api(self):
        result = report([api(output=200), generic(backend='api', provider='openai')])
        self.assertEqual(result['calls'][0]['status'], 'conflict')
        self.assertIsNone(result['calls'][0]['usage']['outputTokens'])

    def test_uncorrelated_local_and_api_with_same_call_id_count_independently(self):
        self.assertEqual(len(report([api(), generic()])['calls']), 2)

    def test_generic_identity_changed_mid_call_is_conflict(self):
        result = report([generic('started', usage={}), generic(model='other-model')])
        self.assertEqual(result['calls'][0]['status'], 'conflict')

    def test_aggregate_rate_sums_matched_pairs_not_average(self):
        result = report([api(output=100, elapsed=1), api(output=100, elapsed=9, ident='b'),
                         api(output=200, elapsed=None, ident='c'), api(output=None, ident='d')])
        group = result['groups'][0]
        self.assertEqual(group['rates']['effectiveRequestTokensPerSecond']['value'], 20)
        self.assertEqual(group['rates']['effectiveRequestTokensPerSecond']['matchedCallCount'], 2)
        self.assertEqual(group['usage']['outputTokens']['knownSubtotal'], 400)
        self.assertEqual(group['usage']['outputTokens']['missingCallCount'], 1)

    def test_zero_output_and_zero_duration(self):
        result = report([api(output=0), api(elapsed=0, ident='b')])
        self.assertEqual(result['calls'][0]['effectiveRequestTokensPerSecond'], 0)
        self.assertIsNone(result['calls'][1]['effectiveRequestTokensPerSecond'])

    def test_invalid_numerics_never_become_rates(self):
        for value in (True, -1, float('nan'), float('inf'), '100'):
            row = report([api(output=value)])['calls'][0]
            self.assertIsNone(row['usage']['outputTokens'])
            self.assertIsNone(row['effectiveRequestTokensPerSecond'])

    def test_input_immutable_and_unsafe_labels_filtered(self):
        rows = [api()]; saved = copy.deepcopy(rows)
        report(rows)
        self.assertEqual(rows, saved)
        row = api(); row['model'] = 'https://host?api_key=secret'
        self.assertIsNone(report([row])['calls'][0]['model'])


if __name__ == '__main__':
    unittest.main()
