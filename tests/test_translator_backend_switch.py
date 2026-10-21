import copy
import json
import unittest

from tongxing_production.text import budget
from tongxing_production.compute.transports import claude_layer2 as claude
from tongxing_production.text import models
from tongxing_production.compute import provider_limits as limits
from tongxing_production.review import review_budget as ledger
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.orchestration import jobs
from tongxing_production.text import policy as policy_tools
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

    def test_bad_transport_preserves_ledger_and_corrected_retry_succeeds(self):
        def ledger_snapshot():
            return {str(path.relative_to(self.h.auth['root'])): path.read_bytes()
                    for path in self.h.auth['root'].rglob('*') if path.is_file()}
        invalid = FakeClaudeTransport()
        invalid.model = 'claude-haiku-5-5'
        wrong_effort = FakeClaudeTransport()
        wrong_effort.effort = 'medium'
        for transport in (None, invalid, wrong_effort):
            caller = self.caller(claude_transport=transport)
            before = ledger_snapshot()
            with self.assertRaisesRegex(ValueError, 'claude_transport_required'):
                caller('', self.payload)
            self.assertEqual(ledger_snapshot(), before)
            if transport is not None:
                self.assertEqual(transport.calls, [])
        corrected = FakeClaudeTransport()
        response = self.caller(claude_transport=corrected)('', self.payload)
        self.assertEqual(response['model'], CLAUDE)
        self.assertEqual(corrected.calls, [('', 'translator')])
        data = jobs._read(self.h.auth['root'] / ledger.STORE_ID / 'state.json')
        self.assertEqual(len(data['reservations']), 1)

    def test_missing_cli_usage_fails_closed_after_request(self):
        broken = cli_result()
        broken['usage']['outputTokens'] = None
        with self.assertRaisesRegex(ValueError, 'claude_language_usage_missing'):
            self.caller(claude_transport=FakeClaudeTransport(broken))('', self.payload)


class ClaudeCliOpusBackendTests(unittest.TestCase):
    """claude_cli_opus: translator Opus high and reviewer Opus medium, both through the subscription CLI."""

    def setUp(self):
        from tests.test_canonical_layer2_budget import CanonicalLayer2BudgetTests
        setup = CanonicalLayer2BudgetTests('test_provider_payload_cap_is_enforced_before_transport')
        setup.setUp()
        self.addCleanup(setup.fixture.doCleanups)
        self.h = setup
        self.policy = copy.deepcopy(setup.policy)
        self.policy['translator'].update(model=CLAUDE, reasoningEffort='high')
        self.policy['reviewer'].update(model=CLAUDE, reasoningEffort='medium')

    def payload(self, effort):
        return budget.limits.bounded_payload({
            'model': CLAUDE, 'reasoning_effort': effort,
            'messages': [{'role': 'system', 'content': 'instruction'}, {'role': 'user', 'content': 'A full sentence.'}],
            'response_format': {'type': 'json_object'}}, self.h.limits)

    def transports(self):
        translator, reviewer = FakeClaudeTransport(), FakeClaudeTransport()
        reviewer.effort = 'medium'
        return {'translator': translator, 'reviewer': reviewer}

    def test_backend_names_both_roles_and_the_runner_dispatches_it(self):
        self.assertEqual(policy_tools.layer2_backend(self.policy), 'claude_cli_opus')
        self.assertEqual(models.production_backend(self.policy), 'claude_cli_opus')
        self.assertEqual(models.production_models(self.policy), {'translator': CLAUDE, 'reviewer': CLAUDE})
        self.assertEqual(models.production_efforts(self.policy), {'translator': 'high', 'reviewer': 'medium'})
        # The historical Opus-translator beside the Sol reviewer is still not a production backend.
        with self.assertRaisesRegex(ValueError, 'experimental_only'):
            models.production_backend(translator_policy(CLAUDE, 'high'))

    def test_each_role_goes_to_its_own_cli_transport_without_an_api_key(self):
        transports = self.transports()
        caller = budget.BudgetedCaller(self.h.auth, self.h.config, self.h.source, self.h.anchor, self.policy,
                                       claude_transports=transports)
        # The fixture budget fits one list-price reservation; the translator path is covered above.
        response = caller('sk-openai-must-not-leak', self.payload('medium'))
        self.assertEqual((transports['translator'].calls, transports['reviewer'].calls), ([], [('', 'reviewer')]))
        self.assertEqual(response['model'], CLAUDE)
        data = jobs._read(self.h.auth['root'] / ledger.STORE_ID / 'state.json')
        self.assertEqual([row['request']['kind'] for row in data['reservations'].values()], ['review'])

    def test_a_claude_reviewer_needs_the_claude_cli_opus_policy(self):
        sol_reviewer = copy.deepcopy(self.policy)
        sol_reviewer['reviewer'].update(model='gpt-6.1-sol', reasoningEffort='medium')
        with self.assertRaisesRegex(ValueError, 'claude_reviewer_requires_claude_cli_opus_policy'):
            budget.BudgetedCaller(self.h.auth, self.h.config, self.h.source, self.h.anchor, sol_reviewer,
                                  claude_transports=self.transports())
        missing = {'translator': self.transports()['translator']}
        caller = budget.BudgetedCaller(self.h.auth, self.h.config, self.h.source, self.h.anchor, self.policy,
                                       claude_transports=missing)
        with self.assertRaisesRegex(ValueError, 'claude_transport_required'):
            caller('', self.payload('medium'))

    def test_controller_builds_one_subscription_transport_per_role(self):
        from pathlib import Path
        from unittest import mock
        from tongxing_production.text import controller
        built = []

        class Recording:
            def __init__(self, *, model, effort, receipts_dir):
                built.append((model, effort, receipts_dir))
        with mock.patch.object(claude, 'ClaudeLayer2Transport', Recording):
            transports = controller.claude_transports(self.policy, {'output': Path('/lane')})
        self.assertEqual(sorted(transports), ['reviewer', 'translator'])
        self.assertEqual(sorted(built), [(CLAUDE, 'high', Path('/lane/claude-calls')),
                                         (CLAUDE, 'medium', Path('/lane/claude-calls'))])

    def test_claude_cache_identity_follows_transports_not_revision_budget(self):
        from tongxing_production.text import controller
        transports = self.transports()
        for role, transport in transports.items():
            transport.execution_identity = {'model': CLAUDE, 'role': role, 'effort': transport.effort}
        first = controller.claude_model_transport_identity(transports)
        # A QC revision has a new budget authorization; its unchanged groups must
        # still prove the same model payload and transport fingerprint.
        second = controller.claude_model_transport_identity(transports)
        self.assertEqual(first, second)
        self.assertNotIn('budgetAuthorizationSha256', first)
        transports['reviewer'].execution_identity = {**transports['reviewer'].execution_identity,
                                                     'effort': 'high'}
        self.assertNotEqual(first, controller.claude_model_transport_identity(transports))


class ClaudeCliOpusPlanTests(unittest.TestCase):
    """The planner caps a claude_cli_opus Layer 2 by list price, outside the approved USD total."""

    def test_claude_layer2_cap_is_a_list_price_equivalent_outside_the_total(self):
        from scripts import plan_run_budgets as planner
        profile = json.loads((planner.PROFILE).read_text())
        self.assertEqual(profile['schemaVersion'], planner.PROFILE_SCHEMA)
        self.assertEqual(planner.layer2_cap_per_locale(profile, 'clip', 'claude_cli_opus'), (8.0, False))
        self.assertEqual(planner.layer2_cap_per_locale(profile, 'clip', 'openai_api'), (2.0, True))
        stages = [{'stage': 'layer2', 'capUsd': 24.0, 'countsTowardTotal': False}, {'stage': 'qc.ko', 'capUsd': 5.525}]
        planned = planner.schedule(stages, total=20, settled=14)
        self.assertEqual((planned['mode'], planned['worstCaseUsd']), ('all_stages_may_run_together', 19.525))
        # A clip's first Opus round (16 groups x 2 calls at list-price worst case) fits the 8 USD cap.
        first_round = 16 * (limits._cost(CLAUDE, 16384, 2048) * 2)
        self.assertLessEqual(first_round, planner.micro(8.0))


if __name__ == '__main__':
    unittest.main()
