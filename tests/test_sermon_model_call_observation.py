import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_model_call_observation as observation


class ModelCallObservationTests(unittest.TestCase):
    def record(self, fill=None, **kwargs):
        events = []
        with patch.object(observation.accounting, '_emit', side_effect=lambda event: events.append(copy.deepcopy(event))):
            with observation.invocation('model-v1', backend='api', provider='provider', role='production', **kwargs) as receipt:
                if fill:
                    receipt.update(fill)
        return [e['fields'] for e in events]

    def test_started_and_finished_identity_missing_is_unknown_not_zero(self):
        start, end = self.record()
        self.assertEqual(start['phase'], 'started')
        self.assertEqual(end['phase'], 'finished')
        self.assertEqual(end['status'], 'completed')
        self.assertEqual(start['callId'], end['callId'])
        self.assertEqual(start['startedAt'], end['startedAt'])
        self.assertEqual(end['usageStatus'], 'unknown')
        self.assertTrue(all(v is None for v in end['usage'].values()))
        self.assertTrue(all(v is None for v in end['rates'].values()))
        self.assertGreaterEqual(end['elapsedSeconds'], 0)

    def test_openai_nested_details_rates_and_explicit_zero(self):
        start, end = self.record({'usage': {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150,
            'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 10}},
            'generationSeconds': 2, 'firstTokenSeconds': 0.1}, usage_source='provider')
        self.assertEqual(end['usageStatus'], 'reported')
        self.assertEqual(end['usage']['cachedInputTokens'], 0)
        self.assertEqual(end['rates']['generationOutputTokensPerSecond'], 25)
        self.assertGreater(end['rates']['requestOutputTokensPerSecond'], 0)
        self.assertIsNone(end['rates']['sessionOutputTokensPerSecond'])
        self.assertEqual(start['usageSource'], 'provider')

    def test_openai_chat_ollama_mlx_and_codex_formats(self):
        for raw, expected in (
            ({'usage': {'prompt_tokens': 7, 'completion_tokens': 4, 'prompt_tokens_details': {'cached_tokens': 3},
                        'completion_tokens_details': {'reasoning_tokens': 2}}}, (7, 4, 3, 2)),
            ({'prompt_eval_count': 7, 'eval_count': 4, 'eval_duration': 2_000_000_000}, (7, 4, None, None)),
            ({'prompt_tokens': 7, 'generation_tokens': 4, 'generation_tps': 2}, (7, 4, None, None)),
            ({'input_tokens': 7, 'output_tokens': 4, 'cached_input_tokens': 3, 'reasoning_output_tokens': 2}, (7, 4, 3, 2)),
        ):
            with self.subTest(raw=raw):
                normalized = observation.normalize_usage(raw)
                self.assertEqual(tuple(normalized[k] for k in ('inputTokens','outputTokens','cachedInputTokens','reasoningTokens')), expected)
        for raw in ({'eval_count': 4, 'eval_duration': 2_000_000_000}, {'generation_tokens': 4, 'generation_tps': 2}):
            self.assertEqual(observation.generation_seconds(raw, observation.normalize_usage(raw)), 2)
        self.assertIsNone(observation.generation_seconds({'generation_tps': 2}, observation.normalize_usage({})))
        self.assertIsNone(observation.normalize_usage({'prompt_tokens': 7, 'completion_tokens': 4})['totalTokens'])

    def test_session_rate_includes_tools_and_no_guessed_generation_rate(self):
        _, end = self.record({'usage': {'output_tokens': 20}}, timing_scope='agent_session_including_tools', usage_source='host_telemetry')
        self.assertEqual(end['usageStatus'], 'partial')
        self.assertIsNotNone(end['rates']['sessionOutputTokensPerSecond'])
        self.assertIsNone(end['rates']['requestOutputTokensPerSecond'])
        self.assertIsNone(end['rates']['generationOutputTokensPerSecond'])

    def test_failed_call_preserves_exception_and_does_not_log_body_or_raw_reply(self):
        events = []
        with patch.object(observation.accounting, '_emit', side_effect=lambda e: events.append(copy.deepcopy(e))):
            with self.assertRaisesRegex(RuntimeError, 'PRIVATE_SECRET'):
                with observation.invocation('model-v1', backend='local', provider='ollama', role='supervisor') as receipt:
                    receipt['usage'] = {'prompt': 'PRIVATE_SECRET', 'headers': {'authorization': 'PRIVATE_SECRET'}}
                    raise RuntimeError('PRIVATE_SECRET')
        self.assertEqual(events[-1]['fields']['status'], 'failed')
        self.assertEqual(events[-1]['fields']['errorType'], 'RuntimeError')
        self.assertNotIn('PRIVATE_SECRET', json.dumps(events))
        self.assertNotIn('headers', json.dumps(events))

    def test_invalid_counts_booleans_and_bad_timing_rejected(self):
        for value in (True, -1, 1.2, '5', float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                observation.normalize_usage({'output_tokens': value})
        for value in (True, -1, float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.record({'generationSeconds': value})
        with self.assertRaises(ValueError):
            self.record({'usage': {'output_tokens': 1}})  # Must name usage evidence source.

    def test_read_validator_rejects_extra_fields_and_invalid_timestamps_rates_labels(self):
        _, base = self.record()
        for key, value in (('prompt', 'private'), ('startedAt', '2026-99-01T00:00:00.000000Z'),
                           ('model', 'arbitrary prompt with spaces'), ('elapsedSeconds', True), ('status', [])):
            modified = copy.deepcopy(base); modified[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                observation.safe_observation(modified)
        modified = copy.deepcopy(base); modified['rates']['generationOutputTokensPerSecond'] = 100
        with self.assertRaises(ValueError): observation.safe_observation(modified)
        self.assertEqual(observation.safe_observation(base), base)

    def test_json_schema_and_python_validator_agree_on_normal_observations(self):
        import jsonschema
        schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas/sermon-model-call-observation-v1.schema.json').read_text())
        for row in self.record({'usage': {'output_tokens': 2}, 'generationSeconds': 1}, usage_source='provider'):
            jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(row)
            observation.safe_observation(row)


if __name__ == '__main__':
    unittest.main()
