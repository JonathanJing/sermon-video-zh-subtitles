"""Offline shared rule preflight and immutable locale version migration."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from scripts import run_bounded_diagnostic_continuation as continuation
from scripts import sermon_strict_locale as locale
from scripts import sermon_review_contracts as c
from scripts import sermon_diagnostic_provider as provider
from tests import test_sermon_strict_locale as fixtures_locale
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class LocaleMigrationTests(unittest.TestCase):
    setUp = fixtures_locale.LocaleTests.setUp
    transport = fixtures_locale.LocaleTests.transport
    run_locale = fixtures_locale.LocaleTests.run_locale
    def legacy(self, remove=()):
        path = self.kw['root'] / 'locale-input.json'
        value, _ = c.read_snapshot(path)
        value['schemaVersion'] = 'sermon-strict-locale-input-v1'
        for key in remove:
            value.pop(key, None)
        path.write_bytes(c.canonical_bytes(value) + b'\n')
        return path, path.read_bytes()

    def test_full_rule_v1_resume_is_explicit_preserves_paid_identity(self):
        with self.f.session():
            result = self.run_locale()
            path, before = self.legacy()
            calls = len(self.f.calls)
            with self.assertRaisesRegex(ValueError, 'strict_locale_legacy_resume_required'):
                self.run_locale()
            again = self.run_locale(resume_legacy=True)
            self.assertEqual(result['output'], again['output'])
            self.assertEqual(calls, len(self.f.calls))
            self.assertEqual(before, path.read_bytes())
            migration, _ = c.read_snapshot(path.parent/'locale-input-migration.json')
            self.assertTrue(migration['completeRuleEvidenceBound'])
            self.assertFalse(migration['humanApproval'])
            self.assertEqual(c.read_snapshot(path.parent/'locale-input-v2.json')[0]['schemaVersion'],
                             'sermon-strict-locale-input-v2')

    def assert_unproven(self, removed):
        with self.f.session():
            self.run_locale()
            path, before = self.legacy(removed)
            cached = {str(p):p.read_bytes() for p in (path.parent/'groups').rglob('*.json')}
            calls = len(self.f.calls)
            result = self.run_locale(resume_legacy=True)
            self.assertEqual(result['reasonCode'], 'strict_locale_legacy_rules_not_proven')
            self.assertTrue(result['requiresNewRevision'])
            self.assertEqual(len(result['preservedGroupRoots']), len(self.plan))
            self.assertEqual(len(self.f.calls), calls)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(cached, {str(p):p.read_bytes() for p in (path.parent/'groups').rglob('*.json')})

    def test_unproven_legacy_rules_preserve_cache_without_calls(self):
        self.assert_unproven(('rulePreflight', 'ruleContext'))

    def test_receipt_only_legacy_rules_preserve_cache_without_calls(self):
        self.assert_unproven(('ruleContext',))

    def test_migration_sidecar_tamper_and_input_drift_refused(self):
        with self.f.session():
            self.run_locale()
            path, before = self.legacy()
            self.run_locale(resume_legacy=True)
            sidecar = path.parent/'locale-input-migration.json'
            altered, _ = c.read_snapshot(sidecar)
            altered['humanApproval'] = True
            sidecar.write_bytes(c.canonical_bytes(altered)+b'\n')
            calls = len(self.f.calls)
            with self.assertRaisesRegex(ValueError, 'immutable_strict_artifact_changed'):
                self.run_locale(resume_legacy=True)
            self.assertEqual(calls, len(self.f.calls))
            self.assertEqual(before, path.read_bytes())


class SharedPreflightTests(unittest.TestCase):
    def setUp(self):
        self.f = DiagnosticDAGFixture();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.spec = self.f.locale_specs['zh-Hans']

    def test_shared_preflight_uses_actual_rule_expanded_prepared_objects(self):
        observed=[]
        class Subject:
            limits=self.f.request_limits
            def preflight_locale(self, prepared): observed.extend(prepared)
        raw, plan = continuation.preflight_locale_inputs(Subject(), self.f.continuation['diagnosticContext'], self.spec)
        actual = locale.prepare_locale_inputs(*raw, plugin_path=self.spec['pluginPath'],
            expected_plugin_sha256=self.spec['pluginSha256'], group_plan=self.spec['groupPlan'],
            request_limits=self.f.request_limits, diagnostic_context=self.f.continuation['diagnosticContext'])[-1]
        self.assertEqual(observed, actual)
        self.assertTrue(all('rulePreflight' in item and 'ruleContext' in item for item in observed))

    def test_quote_group_rules_fail_before_provider_or_credentials(self):
        from scripts import produce_target_language_candidate as producer
        plugin=Path(self.spec['pluginPath'])
        source,_=c.read_snapshot(Path(self.spec['source']))
        anchor,_=c.read_snapshot(Path(self.spec['anchor']))
        unit=anchor['sourceUnits'][0]
        with plugin.open('a') as stream:
            stream.write('\nQUOTED_UNITS = '+repr({unit['sourceUnitId']:(unit['english'],'完整引文。')})+'\n')
        policy_path=Path(self.spec['policy'])
        policy,_=c.read_snapshot(policy_path)
        policy['scripture']['quoteCheckPolicy']='source_bound_exact_quote'
        sha=producer.plugin_implementation_sha256(plugin)
        policy['languageReview']['pluginImplementationSha256']=sha
        for key in ('languageReview','scripture'):
            policy['componentSha256'][key]=c.canonical_sha256(policy[key])
        policy_path.write_bytes(c.canonical_bytes(policy)+b'\n')
        spec={**self.spec,'pluginSha256':sha,'groupPlan':[{'translationGroupId':'merged',
            'sourceUnitIds':[row['sourceUnitId'] for row in anchor['sourceUnits']]}]}
        class Subject:
            limits=self.f.request_limits
            def preflight_locale(self, prepared):
                raise AssertionError('provider must not be reached')
        with self.assertRaisesRegex(ValueError,'exact quote must occupy'):
            continuation.preflight_locale_inputs(Subject(),self.f.continuation['diagnosticContext'],spec)

    def test_expanded_rule_input_cap_is_rejected_by_shared_preflight(self):
        # Same real provider validator as preflight_live, without a credential.
        from scripts import sermon_review_budget as budget
        from scripts import sermon_strict_layer2 as strict
        from scripts import sermon_provider_limits as limits
        raw=[Path(self.spec[key]).read_bytes() for key in ('source','anchor','policy','rubric')]
        checked=locale.prepare_locale_inputs(*raw,plugin_path=self.spec['pluginPath'],
            expected_plugin_sha256=self.spec['pluginSha256'],group_plan=self.spec['groupPlan'],
            request_limits=self.f.request_limits,diagnostic_context=self.f.continuation['diagnosticContext'])[-1][0]
        old=strict.prepare(*raw,self.spec['groupPlan'][0],request_limits=self.f.request_limits,
            diagnostic_context=self.f.continuation['diagnosticContext'])
        cap=limits._input_upper_bound(strict._payload(checked,'translator',strict.prompt(checked,'translator')))-1
        self.assertLess(limits._input_upper_bound(strict._payload(old,'translator',strict.prompt(old,'translator'))),cap)
        frozen={**self.f.request_limits,'maxInputTokens':cap}
        subject=provider.DiagnosticProvider(budget.BudgetStore(self.f.root/'budget',self.f.plan['authority']),
            self.f.plan['providerConfig'],frozen)
        with self.assertRaisesRegex(ValueError, 'provider_input_bound_exceeded'):
            continuation.preflight_locale_inputs(subject,self.f.continuation['diagnosticContext'],self.spec)
        self.assertEqual(len(self.f.transport.observations), 2)
