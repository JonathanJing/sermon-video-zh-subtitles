"""Real producer paths retain deterministic work when group parents are excluded."""
import copy
import time
import unittest
from unittest.mock import patch

from scripts import run_target_language_models as runner
from scripts import sermon_accounting as accounting
from scripts import weekly_pipeline_report as weekly
from tests import test_run_target_language_models as fixture_module


class Layer2LeafAccountingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.RunTargetLanguageModelsTests('test_korean_spoken_revision_can_close_a_complete_clause')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.fixture
        self.out = self.fixture.out

    def run_producer(self, out=None, caller=None, **options):
        out = out or self.out
        with accounting.accounting_session(out / 'accounting', 'layer2_models'):
            result = runner.run(self.f.source, self.f.anchor, self.f.policy, out,
                                'fixture-key', caller or self.fixture.fake_call, **options)
        events, damaged = accounting.read_events(out / 'accounting')
        self.assertFalse(damaged)
        report = weekly.project(out / 'accounting')['runs'][-1]
        return result, events, report

    def test_actual_admission_validation_and_assembly_are_measured_leaves(self):
        original_prepare = runner.producer.prepare_request
        original_coverage = runner._coverage_substring
        original_save = runner.save_new
        def source(*args, **kwargs):
            time.sleep(.02)
            return original_prepare(*args, **kwargs)
        def coverage(*args, **kwargs):
            time.sleep(.01)
            return original_coverage(*args, **kwargs)
        def save(path, value):
            if path.name == 'evidence.json':
                time.sleep(.02)
            return original_save(path, value)
        with patch.object(runner.producer, 'prepare_request', side_effect=source), \
             patch.object(runner, '_coverage_substring', side_effect=coverage), \
             patch.object(runner, 'save_new', side_effect=save):
            _, events, report = self.run_producer()
        self.assertEqual(report['status'], 'projected', report['diagnostics'])
        units = {row['stage']: row for row in report['workUnits']}
        for prefix in ('layer2.source_admission.', 'layer2.draft_validation.',
                       'layer2.review_validation.', 'layer2.evidence_assembly.'):
            selected = [row for name, row in units.items() if name.startswith(prefix)]
            self.assertTrue(selected, prefix)
            self.assertTrue(all(row['executorType'] == 'deterministic_program' for row in selected))
            self.assertTrue(all(row['elapsedSeconds'] >= .01 for row in selected))
        self.assertFalse(any(name.startswith('layer2.group.') for name in units))
        self.assertGreaterEqual(report['leafElapsedByExecutor']['deterministic_program'], .08)
        self.assertIsNotNone(report['criticalPath'])
        starts = {e['spanId']: e for e in events if e['event'] == 'stage_started'}
        assembly = next(e for e in starts.values() if e['stage'].startswith('layer2.evidence_assembly.'))
        self.assertEqual(len(assembly['dependsOn']), 2)
        self.assertTrue(all(starts[x]['stage'].startswith('layer2.review_validation.') for x in assembly['dependsOn']))
        self.assertEqual(len(self.fixture.calls), 4)

    def test_complete_group_reuse_keeps_copy_and_validation_time_without_paid_calls(self):
        old, _, _ = self.run_producer()
        original = runner.carry_forward_group
        def carry(*args, **kwargs):
            time.sleep(.02)
            return original(*args, **kwargs)
        with patch.object(runner, 'carry_forward_group', side_effect=carry):
            reused, events, report = self.run_producer(self.out.parent / 'reused',
                caller=lambda *_: self.fail('reused group invoked a model'), reuse_from=self.out)
        self.assertEqual(reused, old)
        self.assertEqual(report['status'], 'projected', report['diagnostics'])
        self.assertEqual(report['leafElapsedByExecutor']['production_model'], 0)
        prepared = [e for e in events if e['event'] == 'stage_finished' and e['stage'].startswith('layer2.prepare.')]
        self.assertEqual(len(prepared), 2)
        self.assertTrue(all(e['cacheHit'] and e['elapsedSeconds'] >= .02 for e in prepared))
        self.assertGreaterEqual(report['leafElapsedByExecutor']['deterministic_program'], .04)
        starts = {e['spanId']: e for e in events if e['event'] == 'stage_started'}
        assembly = next(e for e in starts.values() if e['stage'].startswith('layer2.evidence_assembly.'))
        self.assertTrue(all(starts[x]['stage'].startswith('layer2.prepare.') for x in assembly['dependsOn']))

    def test_failed_review_validation_is_timed_without_assembling_evidence(self):
        caller = self.fixture.fake_call
        def failed(key, payload):
            answer = caller(key, payload)
            if payload['reasoning_effort'] == self.f.policy['reviewer']['reasoningEffort']:
                # Keep the paid response shape; change only its semantic result.
                import json
                content = json.loads(answer['choices'][0]['message']['content'])
                content['semanticReview']['status'] = 'fail'
                answer['choices'][0]['message']['content'] = json.dumps(content)
            return answer
        with self.assertRaises(ValueError), accounting.accounting_session(self.out / 'accounting', 'layer2_models'):
            runner.run(self.f.source, self.f.anchor, self.f.policy, self.out, 'fixture-key', failed)
        events, damaged = accounting.read_events(self.out / 'accounting')
        self.assertFalse(damaged)
        failed_spans = [e for e in events if e['event'] == 'stage_finished' and e['stage'].startswith('layer2.review_validation.')]
        self.assertEqual(len(failed_spans), 1)
        self.assertEqual(failed_spans[0]['status'], 'failed')
        self.assertFalse((self.out / 'evidence.json').exists())

    def test_accounted_entry_validates_source_once_and_retains_source_failure_gate(self):
        original = runner.producer.prepare_request
        with patch.object(runner.producer, 'prepare_request', wraps=original) as checked:
            evidence = runner.run_accounted(self.f.source, self.f.anchor, self.f.policy, self.out,
                'fixture-key', self.fixture.fake_call, None, self.f.plugin_path, None, None)
        self.assertEqual(checked.call_count, 1)
        self.assertEqual(len(evidence['groups']), 2)
        damaged_source = copy.deepcopy(self.f.source)
        damaged_source['source']['media'] = None
        with self.assertRaises(ValueError):
            runner.run_accounted(damaged_source, self.f.anchor, self.f.policy, self.out.parent / 'bad',
                'fixture-key', lambda *_: self.fail('invalid source reached model'), None, self.f.plugin_path, None, None)

    def test_failed_assembly_logging_never_exports_a_completion_dependency(self):
        completion = []
        original = accounting._emit
        def fail_finish(event):
            if event.get('event') == 'stage_finished' and event.get('stage', '').startswith('layer2.evidence_assembly.'):
                raise accounting.AccountingWriteError('fixture_final_log_failure')
            return original(event)
        with patch.object(accounting, '_emit', side_effect=fail_finish):
            with self.assertRaises(accounting.AccountingWriteError):
                runner.run_accounted(self.f.source, self.f.anchor, self.f.policy, self.out,
                    'fixture-key', self.fixture.fake_call, None, self.f.plugin_path, None, None,
                    completion_spans=completion)
        self.assertEqual(completion, [])
        self.assertTrue((self.out / 'evidence.json').exists())
        self.assertEqual(len(self.fixture.calls), 4)
