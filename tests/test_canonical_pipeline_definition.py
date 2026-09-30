import copy
import json
import unittest
from scripts import canonical_pipeline_definition as p


class CanonicalPlanningTests(unittest.TestCase):
    def setUp(self):
        self.spec = p.definition()
        self.source = 'a' * 64
        self.observations, self.approvals = {}, {}

    def plan(self):
        return p.plan(self.spec, input_identity=self.source, observations=self.observations, approvals=self.approvals)

    def complete(self, ident, output='b' * 64):
        state = self.plan()['nodes'][ident]
        self.approvals[ident] = {gate: {'identity': state['identity'], 'receiptSha256': 'c' * 64}
                                for gate in state['missingGates']}
        self.observations[ident] = {'identity': state['identity'], 'status': 'validated', 'outputSha256': output}

    def test_three_locale_dag_requires_each_audio_package_and_convergence(self):
        self.complete('source')
        for locale in p.LOCALES:
            self.complete('text.' + locale)
            self.complete('audio.' + locale)
            self.complete('page.' + locale)
        self.assertEqual(self.plan()['status'], 'terminal_evidence_observed')
        self.assertFalse(self.plan()['dispatchEnabled'])
        self.assertEqual(self.plan()['productionAcceptance'], 'not_evaluated')
        self.assertEqual(self.plan()['deviceAcceptance'], 'not_run')

    def test_source_and_locale_changes_invalidate_only_correct_descendants(self):
        self.complete('source')
        for locale in p.LOCALES:
            self.complete('text.' + locale)
            self.complete('audio.' + locale)
            self.complete('page.' + locale)
        self.observations['text.ko']['outputSha256'] = 'd' * 64
        states = self.plan()['nodes']
        self.assertEqual(states['page.zh-Hans']['status'], 'validated')
        self.assertEqual(states['page.es']['status'], 'validated')
        self.assertEqual(states['audio.ko']['status'], 'human_gate')
        self.assertEqual(states['page.ko']['status'], 'waiting_dependency')
        self.source = 'e' * 64
        self.assertTrue(all(self.plan()['nodes']['text.' + locale]['status'] == 'waiting_dependency' for locale in p.LOCALES))

    def test_text_only_is_explicit_layer3_and_needs_bound_plan_gate(self):
        self.spec = p.definition(text_only=('ko',))
        self.complete('source'); self.complete('text.ko')
        state = self.plan()['nodes']['audio.ko']
        self.assertEqual(state['missingGates'], ['translation_review', 'text_only_plan'])
        self.assertEqual(self.plan()['nodes']['page.ko']['status'], 'waiting_dependency')
        self.complete('audio.ko')
        self.assertEqual(self.plan()['nodes']['page.ko']['status'], 'ready')

    def test_unknown_outcome_waits_without_retry_and_other_locale_progresses(self):
        self.complete('source')
        identity = self.plan()['nodes']['text.ko']['identity']
        self.observations['text.ko'] = {'identity': identity, 'status': 'uncertain'}
        self.assertEqual(self.plan()['nodes']['text.ko']['status'], 'reconciliation_required')
        self.assertEqual(self.plan()['nodes']['text.es']['status'], 'ready')

    def test_changed_inputs_do_not_abandon_prior_running_job(self):
        self.complete('source')
        identity = self.plan()['nodes']['text.ko']['identity']
        self.observations['text.ko'] = {'identity': identity, 'status': 'running'}
        self.observations['source']['outputSha256'] = 'e' * 64
        self.assertEqual(self.plan()['nodes']['text.ko']['status'], 'reconciliation_required')
        self.assertEqual(self.plan()['nodes']['text.es']['status'], 'ready')

    def test_delivery_scope_and_definition_change_require_new_bindings(self):
        self.complete('source')
        self.spec = p.definition(terminal_scope='delivery_complete')
        self.assertEqual(self.plan()['nodes']['source']['status'], 'human_gate')
        self.assertEqual(self.spec['terminalDependencies'], ['record.es', 'record.ko', 'record.zh-Hans'])
        self.spec['nodes'][0]['human_gates'] = ()
        with self.assertRaises(ValueError): self.plan()

    def test_plan_is_pure_and_unknown_tracker_fields_grant_nothing(self):
        before = copy.deepcopy((self.spec, self.observations, self.approvals))
        self.spec = json.loads(json.dumps(self.spec))
        self.plan()
        self.assertEqual(before, (self.spec, self.observations, self.approvals))
        self.approvals['source'] = {'source_review': {'approved': True, 'status': 'completed'}}
        self.assertEqual(self.plan()['nodes']['source']['status'], 'human_gate')
        self.observations['L1-04'] = {'status': 'completed'}
        with self.assertRaises(ValueError): self.plan()
