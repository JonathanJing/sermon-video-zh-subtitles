"""Offline initial-round reservation; never dispatches a model."""
import copy
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest import mock

from scripts import plan_run_budgets as plan
from scripts import sermon_provider_limits as limits
from tests import test_canonical_layer2_controller as controller_fixtures


class RunBudgetInputFeasibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = controller_fixtures.CanonicalLayer2ControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.profile = json.loads(plan.PROFILE.read_text())
        self.execution = self.fixture.path
        self.locales = ['zh-Hans']

    def spec(self, profile=None):
        return plan.layer2_spec(self.execution, self.locales, profile or self.profile, 'clip')

    def invoke(self, profile, name):
        profile_path = self.fixture.root / (name + '-profile.json')
        profile_path.write_text(json.dumps(profile))
        out = self.fixture.root / name
        args = ['--out', str(out), '--scale', 'clip', '--locales', 'zh-Hans',
                '--stage', 'layer2', '--total-usd', '20', '--approved-by', 'Offline fixture',
                '--evidence', 'Injected fixtures; no paid calls', '--layer2-execution', str(self.execution),
                '--profile', str(profile_path)]
        with contextlib.redirect_stdout(io.StringIO()), mock.patch('urllib.request.urlopen', side_effect=AssertionError('dispatch')):
            result = plan.main(args)
        return result, out

    def test_initial_reservation_covers_both_roles_and_unknown_maximum_reviewer_draft(self):
        _, _, sizing = self.spec()
        value = sizing['zh-Hans']; initial = value['initialReservation']
        selected = self.profile['layer2']['requestLimits']
        groups = value['groups']
        self.assertGreater(groups, 0)
        self.assertEqual(initial['requests'], 2 * groups)
        self.assertEqual(initial['inputTokens'], 2 * groups * selected['maxInputTokens'])
        self.assertEqual(initial['outputTokens'], 2 * groups * selected['maxCompletionTokens'])
        self.assertEqual(initial['wallTimeMs'], 2 * groups * selected['wallTimeMs'])
        policy = self.fixture.fixture.fixture.policy
        self.assertEqual(initial['costMicrousd'], groups * sum(limits._cost(policy[role]['model'],
            selected['maxInputTokens'], selected['maxCompletionTokens']) for role in ('translator', 'reviewer')))
        self.assertGreater(initial['costMicrousd'], value['initialOutputReservationMicrousd'])
        # Actual serialized reviewer inputs include generated text, UTF-8 and
        # JSON escaping. The ceiling safely covers every admitted payload;
        # generation beyond it is rejected, never silently counted as free.
        from scripts.run_target_language_models import model_payload
        for candidate in ('한글' * 300, '\\"\n' * 500):
            payload = model_payload('reviewer', {'instruction': 'Review source and draft',
                'input': {'englishUnits': [{'english': 'Source'}], 'astraDraft': candidate}}, policy, selected)
            measured_bound = limits.request_bounds(payload, selected)
            self.assertLessEqual(measured_bound['inputTokens'], initial['inputTokens'] // (2 * groups))
        with self.assertRaisesRegex(ValueError, 'provider_input_bound_exceeded'):
            model_payload('reviewer', {'instruction': 'Review', 'input': {'astraDraft': '한' * 20000}}, policy, selected)

    def test_each_initial_dimension_shortfall_refuses_before_any_authority(self):
        initial = self.spec()[2]['zh-Hans']['initialReservation']
        for dimension in initial:
            with self.subTest(dimension=dimension):
                profile = copy.deepcopy(self.profile)
                if dimension == 'costMicrousd':
                    profile['layer2']['capUsdPerLocale']['clip'] = (initial[dimension] - 1) / 1_000_000
                else:
                    profile['layer2']['boundsPerLocale']['clip'][dimension] = initial[dimension] - 1
                out = self.fixture.root / ('short-' + dimension)
                with self.assertRaisesRegex(ValueError, dimension):
                    self.invoke(profile, out.name)
                self.assertFalse(out.exists())
                self.assertFalse(list(self.fixture.root.glob(out.name + '/**/*approval*.json')))

    def test_output_only_affordable_budget_no_longer_issues_authority(self):
        value = self.spec()[2]['zh-Hans']
        profile = copy.deepcopy(self.profile)
        profile['layer2']['capUsdPerLocale']['clip'] = value['initialOutputReservationMicrousd'] / 1_000_000
        with self.assertRaisesRegex(ValueError, 'costMicrousd'):
            self.invoke(profile, 'output-only')
        self.assertFalse((self.fixture.root / 'output-only').exists())

    def test_exact_five_dimension_initial_bound_can_issue_frozen_authority(self):
        initial = self.spec()[2]['zh-Hans']['initialReservation']
        profile = copy.deepcopy(self.profile)
        profile['layer2']['boundsPerLocale']['clip'] = {k: v for k, v in initial.items() if k != 'costMicrousd'}
        profile['layer2']['capUsdPerLocale']['clip'] = initial['costMicrousd'] / 1_000_000
        code, out = self.invoke(profile, 'exact')
        self.assertEqual(code, 0)
        saved = json.loads((out / 'plan.json').read_text())
        self.assertEqual(saved['stages'][0]['sizing']['zh-Hans']['initialReservation'], initial)
        authorization = json.loads(Path(saved['stages'][0]['authorization']).read_text())
        self.assertEqual(authorization['authority']['globalBounds'], initial)
