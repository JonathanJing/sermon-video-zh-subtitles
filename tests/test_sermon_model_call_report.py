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


def codex(**overrides):
    from scripts.codex_credit_usage import estimate_credit_usage
    usage = dict(inputTokens=1000, cachedInputTokens=400, outputTokens=200,
                 totalTokens=1200, reasoningTokens=75)
    fields = dict(schemaVersion='sermon-model-call-observation-v2', model='gpt-6.1-sol',
                  backend='agent_session', provider='codex', role='production',
                  timingScope='agent_session_including_tools', usage=usage,
                  cacheHit=None, generationSeconds=None)
    fields.update(overrides)
    if 'creditUsage' not in overrides:
        fields['creditUsage'] = estimate_credit_usage(
            fields['model'], fields['usage'], requested_service_tier='fast',
            status=fields.get('status', 'completed'), cache_hit=fields.get('cacheHit'))
    return generic(**fields)


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

    def test_codex_credit_snapshot_preserved_and_aggregated(self):
        receipt = codex(); saved = copy.deepcopy(receipt)
        result = report([receipt]); row = result['calls'][0]
        self.assertEqual(result['schemaVersion'], 'sermon-model-call-report-v2')
        self.assertEqual(row['creditUsage'], receipt['fields']['creditUsage'])
        self.assertEqual(receipt, saved)
        self.assertIsNot(row['creditUsage'], receipt['fields']['creditUsage'])
        self.assertEqual(result['creditUsage']['estimatedCreditsKnownSubtotal'], row['creditUsage']['estimatedCredits'])
        self.assertEqual(result['creditUsage']['estimatedCallCount'], 1)
        self.assertEqual(result['creditUsage']['unknownCallCount'], 0)
        self.assertTrue(result['creditUsage']['complete'])
        self.assertIsNone(result['creditUsage']['actualCredits'])
        self.assertIsNone(result['creditUsage']['actualQuotaUsage'])
        self.assertEqual(result['groups'][0]['creditUsage'], result['creditUsage'])

    def test_codex_historical_tier_unknown_is_not_backfilled(self):
        result = report([codex(schemaVersion='sermon-model-call-observation-v1', creditUsage=None)])
        credit = result['calls'][0]['creditUsage']
        self.assertEqual(credit['status'], 'unknown')
        self.assertIsNone(credit['estimatedCredits'])
        self.assertIsNone(credit['requestedServiceTier'])
        self.assertFalse(result['creditUsage']['complete'])
        self.assertEqual(result['creditUsage']['estimatedCreditsKnownSubtotal'], 0)
        self.assertEqual(result['creditUsage']['unknownCallCount'], 1)

    def test_codex_sdk_supervisor_unknown_credit_identity(self):
        end = event('sdk_call_finished', invocationId='i', model='gpt-6.1-sol', agentBackend='codex',
                    status='completed', elapsedSeconds=10, usage={'input_tokens': 1000, 'output_tokens': 200})
        result = report([end])
        self.assertEqual(result['calls'][0]['provider'], 'not_recorded')
        self.assertEqual(result['calls'][0]['creditUsage']['status'], 'unknown')
        self.assertEqual(result['creditUsage']['unknownCallCount'], 1)

    def test_api_and_local_never_contribute_codex_credits(self):
        injected = codex()['fields']['creditUsage']
        result = report([api(creditUsage=injected), generic(creditUsage=injected)])
        self.assertIsNone(result['creditUsage'])
        self.assertTrue(all('creditUsage' not in row for row in result['calls']))
        self.assertTrue(all('creditUsage' not in row for row in result['groups']))

    def test_cached_input_discount_is_not_cache_reuse(self):
        result = report([codex()])
        self.assertGreater(result['creditUsage']['estimatedCreditsKnownSubtotal'], 0)
        self.assertEqual(result['creditUsage']['cacheReuseCallCount'], 0)

    def test_explicit_cache_reuse_records_zero_estimate(self):
        result = report([codex(cacheHit=True, usage={})])
        self.assertEqual(result['calls'][0]['creditUsage']['status'], 'cache_reuse')
        self.assertEqual(result['creditUsage']['estimatedCreditsKnownSubtotal'], 0)
        self.assertEqual(result['creditUsage']['cacheReuseCallCount'], 1)
        self.assertTrue(result['creditUsage']['complete'])
        self.assertIsNone(result['creditUsage']['actualCredits'])

    def test_failed_call_with_reported_usage_is_not_free(self):
        result = report([codex(status='failed')])
        self.assertGreater(result['creditUsage']['estimatedCreditsKnownSubtotal'], 0)
        self.assertEqual(result['calls'][0]['creditUsage']['reason'], 'reported_failed_usage_subtotal')

    def test_credit_conflict_suppresses_numeric_evidence(self):
        first = codex(); second = copy.deepcopy(first)
        second['fields']['creditUsage']['estimatedCredits'] += 1
        result = report([first, second])
        self.assertEqual(result['calls'][0]['status'], 'conflict')
        self.assertIsNone(result['calls'][0]['creditUsage']['estimatedCredits'])
        self.assertEqual(result['creditUsage']['estimatedCreditsKnownSubtotal'], 0)
        self.assertEqual(result['creditUsage']['unknownCallCount'], 1)

    def test_codex_requested_tier_changed_mid_call_is_conflict(self):
        from scripts.codex_credit_usage import estimate_credit_usage
        finished = codex(); started = generic(**{
            **finished['fields'], 'phase': 'started', 'status': 'started', 'usage': {},
            'elapsedSeconds': None, 'finishedAt': None, 'creditUsage': estimate_credit_usage(
                'gpt-6.1-sol', {}, requested_service_tier='default', status='started')})
        result = report([started, finished])
        self.assertEqual(result['calls'][0]['status'], 'conflict')
        self.assertIsNone(result['calls'][0]['creditUsage']['estimatedCredits'])

    def test_invalid_recorded_credit_snapshot_is_unknown(self):
        receipt = codex(); receipt['fields']['creditUsage']['estimatedCredits'] += 1
        result = report([receipt])
        self.assertIsNone(result['calls'][0]['creditUsage']['estimatedCredits'])
        self.assertEqual(result['calls'][0]['creditUsage']['reason'], 'malformed_recorded_credit_evidence')
        self.assertEqual(result['creditUsage']['unknownCallCount'], 1)

    def test_same_codex_receipt_imported_across_runs_counts_once(self):
        receipt = codex(); imported = copy.deepcopy(receipt)
        imported.update(runId='other', eventId='imported', recordedAt='2026-10-06T00:00:00Z')
        result = report([receipt, imported])
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['equivalentDuplicatesIgnored'], 1)
        self.assertEqual(result['creditUsage']['estimatedCallCount'], 1)

    def test_codex_import_conflict_is_unknown(self):
        receipt = codex(); imported = copy.deepcopy(receipt)
        imported['runId'] = 'other'
        imported['fields']['usage']['outputTokens'] += 1
        result = report([receipt, imported])
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['calls'][0]['status'], 'conflict')
        self.assertIsNone(result['calls'][0]['creditUsage']['estimatedCredits'])

    def test_codex_same_call_id_different_start_is_separate(self):
        receipt = codex(); other = copy.deepcopy(receipt)
        other['runId'] = 'other'
        other['fields']['startedAt'] = '2026-10-06T00:00:00Z'
        result = report([receipt, other])
        self.assertEqual(len(result['calls']), 2)
        self.assertEqual(result['creditUsage']['estimatedCallCount'], 2)

    def test_codex_missing_start_does_not_cross_run_deduplicate(self):
        receipt = codex(startedAt=None); imported = copy.deepcopy(receipt)
        imported['runId'] = 'other'
        result = report([receipt, imported])
        self.assertEqual(len(result['calls']), 2)

    def test_mixed_codex_credit_coverage_never_conflates_unknown_with_zero(self):
        known = codex(); unknown = codex(callId='b', creditUsage=None)
        result = report([known, unknown, api()])
        self.assertEqual(result['creditUsage']['estimatedCallCount'], 1)
        self.assertEqual(result['creditUsage']['unknownCallCount'], 1)
        self.assertFalse(result['creditUsage']['complete'])
        self.assertGreater(result['creditUsage']['estimatedCreditsKnownSubtotal'], 0)


if __name__ == '__main__':
    unittest.main()
