import copy
import json
import unittest

from scripts import canonical_layer2_budget as budget
from scripts import claude_layer2_transport as claude
from scripts import run_target_language_models as models
from scripts import sermon_provider_limits as limits
from scripts import sermon_review_budget as ledger
from scripts import sermon_workflow_jobs as jobs
from scripts import target_language_policy as policy_tools
from tests import test_canonical_layer2_controller as fixtures


CLAUDE = 'claude-opus-5-5'


def translator_policy(model, effort):
    return {'translator': {'model': model, 'reasoningEffort': effort, 'promptVersion': 'p-t'},
            'reviewer': {'model': 'gpt-6.1-sol', 'reasoningEffort': 'medium', 'promptVersion': 'p-r'}}


def cli_result(model=CLAUDE, input_tokens=1000, output_tokens=200):
    return {'schemaVersion': claude.SCHEMA, 'id': 'claude:session-1', 'sessionId': 'session-1',
            'requestedModel': model, 'reportedModels': [model], 'requestedEffort': 'high',
            'serviceTier': None, 'completed': True, 'exitCode': 0,
            'content': json.dumps({'translation': 'ok'}, ensure_ascii=False),
            'usage': {'inputTokens': input_tokens, 'cachedInputTokens': 0,
                      'outputTokens': output_tokens, 'reasoningTokens': None,
                      'totalTokens': input_tokens + output_tokens},
            'modelUsage': {model: {}}, 'listPriceUsd': 0.01, 'numTurns': 2,
            'elapsedSeconds': 1.0, 'apiDurationMs': 900}


class FakeClaudeTransport:
    """Stands in for ClaudeLayer2Transport; records the key it was given."""
    model, effort = CLAUDE, 'high'

    def __init__(self, result=None):
        self.result, self.calls = result or cli_result(), []

    def __call__(self, api_key, payload, *, role='translator'):
        self.calls.append((api_key, role))
        return self.result


class TranslatorBackendPolicyTests(unittest.TestCase):
    def test_default_openai_policy_keeps_production_models(self):
        policy = translator_policy('gpt-6.1-sol', 'high')
        self.assertEqual(models.translator_backend(policy), 'openai_api')
        self.assertEqual(models.production_models(policy), {'translator': 'gpt-6.1-sol', 'reviewer': 'gpt-6.1-sol'})

    def test_claude_policy_selects_claude_translator_and_keeps_sol_reviewer(self):
        policy = translator_policy(CLAUDE, 'high')
        self.assertEqual(models.translator_backend(policy), 'claude_cli')
        with self.assertRaisesRegex(ValueError, 'experimental_only'):
            models.production_models(policy)

    def test_claude_history_is_recoverable_only_without_dispatch(self):
        policy = translator_policy(CLAUDE, 'high')
        self.assertEqual(models.historical_models(policy, cache_only=True)['translator'], CLAUDE)
        with self.assertRaisesRegex(ValueError, 'unsupported_historical_model_policy'):
            models.historical_models(policy, cache_only=False)
        policy['reviewer']['model'] = CLAUDE
        with self.assertRaisesRegex(ValueError, 'unsupported_historical_model_policy'):
            models.historical_models(policy, cache_only=True)

    def test_claude_effort_or_unknown_model_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'translator_backend_effort_changed'):
            models.translator_backend(translator_policy(CLAUDE, 'medium'))
        with self.assertRaisesRegex(ValueError, 'unsupported_translator_backend'):
            models.translator_backend(translator_policy('claude-haiku-5-5', 'high'))

    def test_apply_translator_backend_changes_only_translator(self):
        draft = {'schemaVersion': 'x', 'translator': {'model': 'gpt-6.1-sol', 'reasoningEffort': 'high',
                                                       'promptVersion': 'p-t'},
                 'reviewer': {'model': 'gpt-6.1-sol', 'reasoningEffort': 'medium', 'promptVersion': 'p-r'}}
        claude_draft = policy_tools.apply_translator_backend(draft, 'claude_cli')
        self.assertEqual(claude_draft['translator'], {'model': CLAUDE, 'reasoningEffort': 'high',
                                                      'promptVersion': 'p-t'})
        self.assertEqual(claude_draft['reviewer'], draft['reviewer'])
        self.assertEqual(draft['translator']['model'], 'gpt-6.1-sol')  # input not mutated
        self.assertEqual(policy_tools.apply_translator_backend(draft, 'openai_api')['translator']['model'],
                         'gpt-6.1-sol')

    def test_apply_translator_backend_refuses_frozen_or_unknown(self):
        with self.assertRaisesRegex(ValueError, 'without component hashes'):
            policy_tools.apply_translator_backend({'componentSha256': {}, 'translator': {}}, 'claude_cli')
        with self.assertRaisesRegex(ValueError, 'Unsupported translator backend'):
            policy_tools.apply_translator_backend({'translator': {}}, 'gemini')

    def test_runner_and_policy_share_one_backend_table(self):
        self.assertIs(models.TRANSLATOR_BACKENDS, policy_tools.TRANSLATOR_BACKENDS)


class ClaudeProviderLimitTests(unittest.TestCase):
    def setUp(self):
        self.limits = dict(budget.limits.DEFAULT_REQUEST_LIMITS)

    def payload(self, model=CLAUDE, effort='high'):
        return {'model': model, 'reasoning_effort': effort,
                'messages': [{'role': 'system', 'content': 'instruction'},
                             {'role': 'user', 'content': 'A full sentence.'}],
                'response_format': {'type': 'json_object'}}

    def test_claude_is_budgeted_but_not_an_openai_supported_model(self):
        self.assertIn(CLAUDE, limits.BUDGET_MODELS)
        self.assertNotIn(CLAUDE, limits.SUPPORTED_MODELS)
        self.assertNotIn(CLAUDE, limits.MODEL_REASONING_EFFORTS)

    def test_bounded_payload_accepts_claude_high_and_refuses_unknown_effort(self):
        bounded = limits.bounded_payload(self.payload(), self.limits)
        self.assertEqual(bounded['model'], CLAUDE)
        with self.assertRaisesRegex(ValueError, 'unsupported_bounded_reasoning_effort'):
            limits.bounded_payload(self.payload(effort='none'), self.limits)

    def test_reservation_uses_list_price_worst_case(self):
        bounds = limits.request_bounds(self.payload(), self.limits)
        upper_inputs, outputs = bounds['inputTokens'], bounds['outputTokens']
        self.assertEqual(bounds['costMicrousd'], 8 * upper_inputs + 20 * outputs)
        self.assertEqual(limits.PRICE_ASSUMPTION_VERSION_BY_MODEL[CLAUDE], 'strict-claude-list-worst-case-2026-10-08-v1')
        self.assertIn('platform.claude.com', limits.PRICE_SOURCES[CLAUDE])


class ClaudeTransportAdapterTests(unittest.TestCase):
    def test_chat_envelope_matches_group_runner_contract(self):
        envelope = claude.chat_envelope(cli_result(), CLAUDE)
        content = models.completed_response_content(envelope, CLAUDE, 'translator')
        self.assertEqual(json.loads(content), {'translation': 'ok'})
        self.assertEqual(envelope['usage'], {'prompt_tokens': 1000, 'completion_tokens': 200, 'total_tokens': 1200})

    def test_chat_envelope_refuses_identity_or_usage_drift(self):
        with self.assertRaisesRegex(ValueError, 'envelope_identity_mismatch'):
            claude.chat_envelope(cli_result(model='claude-haiku-5-5'), CLAUDE)
        broken = cli_result()
        broken['usage']['inputTokens'] = None
        with self.assertRaisesRegex(ValueError, 'usage_missing'):
            claude.chat_envelope(broken, CLAUDE)

    def test_child_environment_drops_openai_and_anthropic_credentials(self):
        environ = {'OPENAI_API_KEY': 'k1', 'OPENAI_PROJECT_ID': 'p1', 'ANTHROPIC_API_KEY': 'k2',
                   'CLAUDE_CODE_SESSION': 's', 'ANTHROPIC_BASE_URL': 'https://bad',
                   'ANTHROPIC_CUSTOM_HEADERS': 'private', 'PATH': '/bin'}
        self.assertEqual(claude.child_environment(environ), {'PATH': '/bin'})


class ClaudeBudgetedCallerTests(unittest.TestCase):
    """Runs the real BudgetedCaller against the controller fixture with a fake CLI transport."""

    def setUp(self):
        from tests.test_canonical_layer2_budget import CanonicalLayer2BudgetTests
        setup = CanonicalLayer2BudgetTests('test_provider_payload_cap_is_enforced_before_transport')
        setup.setUp()
        self.addCleanup(setup.fixture.doCleanups)
        self.h = setup
        self.policy = copy.deepcopy(setup.policy)
        self.policy['translator'].update(model=CLAUDE, reasoningEffort='high')
        self.payload = budget.limits.bounded_payload({
            'model': CLAUDE, 'reasoning_effort': 'high',
            'messages': [{'role': 'system', 'content': 'instruction'},
                         {'role': 'user', 'content': 'A full sentence.'}],
            'response_format': {'type': 'json_object'}}, setup.limits)

    def caller(self, transport=None, claude_transport=None):
        return budget.BudgetedCaller(self.h.auth, self.h.config, self.h.source, self.h.anchor,
                                     self.policy, transport=transport, claude_transport=claude_transport)

    def test_claude_payload_without_claude_transport_is_refused_before_any_call(self):
        openai_calls = []
        with self.assertRaisesRegex(ValueError, 'claude_transport_required'):
            self.caller(transport=lambda *args: openai_calls.append(1))('', self.payload)
        self.assertEqual(openai_calls, [])

    def test_claude_transport_gets_empty_key_and_ledger_records_list_price_cost(self):
        fake = FakeClaudeTransport()
        response = self.caller(claude_transport=fake)('sk-openai-must-not-leak', self.payload)
        self.assertEqual(fake.calls, [('', 'translator')])
        self.assertEqual(response['model'], CLAUDE)
        records = list(self.caller(claude_transport=fake).root.glob('responses/*.json'))
        self.assertEqual(len(records), 1)
        self.assertEqual(jobs._read(records[0])['priceAssumptionVersion'],
                         limits.PRICE_ASSUMPTION_VERSION_BY_MODEL[CLAUDE])
        self.assertEqual(models.completed_response_content(response, CLAUDE, 'translator'),
                         json.dumps({'translation': 'ok'}, ensure_ascii=False))
        data = jobs._read(self.h.auth['root'] / ledger.STORE_ID / 'state.json')
        row = next(iter(data['reservations'].values()))
        self.assertEqual(row['result']['usage']['costMicrousd'], 8 * 1000 + 20 * 200)

    def test_claude_transport_identity_must_match_payload(self):
        fake = FakeClaudeTransport()
        fake.effort = 'medium'
        with self.assertRaisesRegex(ValueError, 'claude_transport_required'):
            self.caller(claude_transport=fake)('', self.payload)

    def test_missing_cli_usage_fails_closed_after_request(self):
        broken = cli_result()
        broken['usage']['outputTokens'] = None
        with self.assertRaisesRegex(ValueError, 'claude_language_usage_missing'):
            self.caller(claude_transport=FakeClaudeTransport(broken))('', self.payload)


if __name__ == '__main__':
    unittest.main()
