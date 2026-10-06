import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema

from scripts import codex_credit_usage as credits
from scripts import sermon_model_call_observation as observation


class CodexCreditUsageTests(unittest.TestCase):
    def usage(self, **updates):
        return dict(inputTokens=1_000_000, cachedInputTokens=400_000,
                    outputTokens=100_000, reasoningTokens=80_000, **updates)

    def test_fast_credit_equivalent_discounts_cache_and_does_not_add_reasoning(self):
        result = credits.estimate_credit_usage('gpt-6.1-sol', self.usage(), requested_service_tier='fast')
        self.assertEqual(result['estimatedCredits'], 112)
        self.assertEqual(result['speedMultiplier'], 2)
        self.assertIsNone(result['actualCredits'])
        self.assertIsNone(result['actualQuotaUsage'])
        self.assertEqual(result['basis'], 'purchased_credit_equivalent')
        self.assertEqual(result['reason'], 'requested_identity_assumption')

    def test_other_models_and_effective_server_identity(self):
        sol = credits.estimate_credit_usage('gpt-6-sol', self.usage(), requested_service_tier='default')
        luna = credits.estimate_credit_usage('gpt-6-luna', self.usage(), requested_service_tier='default')
        self.assertEqual(sol['estimatedCredits'], 57)
        self.assertEqual(luna['estimatedCredits'], 2.85)
        effective = credits.estimate_credit_usage('gpt-6-astra', self.usage(), requested_service_tier='fast',
            server_model='gpt-6.1-sol', server_service_tier='default')
        self.assertEqual(effective['estimatedCredits'], 56)
        self.assertEqual(effective['reason'], 'reported_identity')
        self.assertEqual(effective['tierSource'], 'server')

    def test_missing_or_invalid_counters_do_not_become_free(self):
        for usage in (None, {}, {'inputTokens': 100, 'outputTokens': 2},
                      {'inputTokens': 10, 'cachedInputTokens': 11, 'outputTokens': 2},
                      {'inputTokens': True, 'cachedInputTokens': 0, 'outputTokens': 2}):
            row = credits.estimate_credit_usage('gpt-6-sol', usage, requested_service_tier='fast')
            self.assertEqual(row['status'], 'unknown')
            self.assertIsNone(row['estimatedCredits'])

    def test_missing_tier_and_unknown_models_are_unknown(self):
        for model, tier in (('gpt-6-sol', None), ('new-model', 'fast'), ('gpt-6-sol', 'ultrafast')):
            row = credits.estimate_credit_usage(model, self.usage(), requested_service_tier=tier)
            self.assertEqual(row['status'], 'unknown')
            self.assertIsNone(row['estimatedCredits'])

    def test_ultrafast_astra_uses_paid_credit_six_not_included_eight(self):
        row = credits.estimate_credit_usage('gpt-6-astra', self.usage(), requested_service_tier='ultrafast')
        self.assertEqual(row['estimatedCredits'], 1710)
        self.assertEqual(row['speedMultiplier'], 6)

    def test_failed_reported_usage_is_subtotal_unknown_and_conflict_suppress(self):
        row = credits.estimate_credit_usage('gpt-6-sol', self.usage(), requested_service_tier='fast', status='failed')
        self.assertEqual(row['estimatedCredits'], 114)
        self.assertEqual(row['reason'], 'reported_failed_usage_subtotal')
        for status in ('started', 'interrupted_or_running', 'conflict'):
            row = credits.estimate_credit_usage('gpt-6-sol', self.usage(), requested_service_tier='fast',
                                               status=status, cache_hit=True)
            self.assertIsNone(row['estimatedCredits'])

    def test_cache_reuse_zero_is_separate_from_input_cache_discount(self):
        row = credits.estimate_credit_usage('gpt-6-sol', self.usage(), cache_hit=True)
        self.assertEqual(row['status'], 'cache_reuse')
        self.assertEqual(row['estimatedCredits'], 0)

    def test_zero_usage_validates_and_rate_snapshot_is_strict_content_free(self):
        usage = dict(inputTokens=0, outputTokens=0, cachedInputTokens=0)
        row = credits.estimate_credit_usage('gpt-6-sol', usage, requested_service_tier='default')
        self.assertEqual(row['status'], 'estimated')
        self.assertEqual(row['estimatedCredits'], 0)
        self.assertEqual(credits.safe_credit_usage(row, 'gpt-6-sol', usage), row)
        for key, value in (('estimatedCredits', True), ('actualCredits', 2), ('prompt', 'PRIVATE'),
                           ('rateCardSha256', 'wrong'), ('speedMultiplier', 2.5)):
            altered = {**row, key: value}
            with self.assertRaises(ValueError):
                credits.safe_credit_usage(altered, 'gpt-6-sol', usage)

    def test_codex_only_v2_log_schema_and_recomputed_estimate(self):
        events = []
        with patch.object(observation.accounting, '_emit', side_effect=lambda row: events.append(copy.deepcopy(row))):
            with observation.invocation('gpt-6.1-sol', backend='agent_session', provider='codex',
                    role='supervisor', service_tier='fast', usage_source='host_telemetry',
                    timing_scope='agent_session_including_tools') as receipt:
                receipt['usage'] = self.usage()
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root/'schemas/sermon-model-call-observation-v2.schema.json').read_text())
        for event in events:
            row = event['fields']
            jsonschema.validate(row, schema)
            observation.safe_observation(row)
        self.assertEqual(events[-1]['fields']['creditUsage']['estimatedCredits'], 112)
        self.assertEqual(receipt['creditUsage'], events[-1]['fields']['creditUsage'])
        damaged = copy.deepcopy(events[-1]['fields'])
        damaged['usage']['outputTokens'] += 1
        # Remove derived timing rates to isolate the billing binding.
        damaged['rates']['sessionOutputTokensPerSecond'] = damaged['usage']['outputTokens'] / damaged['elapsedSeconds']
        with self.assertRaisesRegex(ValueError, 'credit_usage'):
            observation.safe_observation(damaged)
        wrong_provider = copy.deepcopy(events[-1]['fields']); wrong_provider['provider'] = 'openai'
        with self.assertRaisesRegex(ValueError, 'requires_codex_session'):
            observation.safe_observation(wrong_provider)


if __name__ == '__main__':
    unittest.main()
