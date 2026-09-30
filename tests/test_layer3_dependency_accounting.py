"""Actual serial render/assembly traces preserve sound and expose leaf dependencies."""
import json
import time
import unittest
from unittest.mock import patch

from scripts import render_formal_target_language_speech as renderer
from scripts import sermon_accounting as accounting
from scripts import weekly_pipeline_report as weekly
from scripts import four_layer_progress as progress
from scripts import four_layer_measure as measure
from tests import test_render_formal_target_language_speech as fixtures


class Layer3DependencyAccountingTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.FormalRenderTests('test_two_units_full_decode_and_resume_without_synthesis')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root, self.paths, self.context = self.f.root, self.f.paths, self.f.context

    def render(self, ledger=None):
        # Checkpoint loading is synthetic; actual render, media decode, schedule,
        # receipts, package validation and accounting are exercised unchanged.
        with patch.object(renderer, 'checked_context', return_value=self.context):
            return renderer.render_accounted(self.paths, self.root / 'checkpoint-map.json',
                self.root / 'audio-operation-policies.json', synth_factory=fixtures.FakeSynth,
                progress_ledger=ledger)

    def report(self, directory=None):
        directory = directory or self.root / 'accounting'
        events, damaged = accounting.read_events(directory)
        self.assertFalse(damaged)
        latest = max((e for e in events if e['event'] == 'run_started'), key=lambda e: e['recordedAt'])
        report = next(r for r in weekly.project(directory)['runs'] if r['runSha256'] == weekly.digest(latest['runId']))
        self.assertEqual(report['status'], 'projected', report['diagnostics'])
        return events, report

    def test_cold_and_warm_renderer_have_complete_serial_dag_and_identical_sound(self):
        first = self.render()
        events, report = self.report()
        starts = {e['spanId']: e for e in events if e['event'] == 'stage_started'}
        named = {e['stage']: e for e in starts.values()}
        edges = {
            'layer3.cache_admission.ko.0000': ['layer3.validate_inputs'],
            'layer3.cache_admission.ko.0001': ['layer3.receipt.ko.0000'],
            'layer3.model_load.ko': ['layer3.cache_admission.ko.0000'],
            'layer3.assembly_admission': ['layer3.receipt.ko.0001'],
            'layer3.schedule': ['layer3.assembly_admission'],
            'layer3.track_assembly': ['layer3.schedule'],
            'layer3.manifest_commit': ['layer3.track_assembly'],
        }
        for stage, predecessors in edges.items():
            self.assertEqual([starts[x]['stage'] for x in named[stage]['dependsOn']], predecessors, stage)
        self.assertEqual(len(fixtures.FakeSynth.calls), 2)
        self.assertGreater(report['leafElapsedByExecutor']['production_model'], 0)
        self.assertAlmostEqual(report['criticalPath']['activeSeconds'],
            sum(row['elapsedSeconds'] for row in report['workUnits']), places=5)
        audio_hashes = [row['audio']['sha256'] for row in first['units']]
        second = self.render()
        warm_events, warm = self.report()
        self.assertEqual(second, first)
        self.assertEqual([row['audio']['sha256'] for row in second['units']], audio_hashes)
        self.assertEqual(len(fixtures.FakeSynth.calls), 2)
        self.assertEqual(warm['leafElapsedByExecutor']['production_model'], 0)
        self.assertTrue(any(row['stage'] == 'layer3.assembly_admission' for row in warm['workUnits']))
        self.assertFalse(any(row['stage'] == 'layer3.track_assembly' for row in warm['workUnits']))
        self.assertEqual(second['machineScreening']['status'], 'not_run')
        warm_admission = next(row for row in warm['workUnits'] if row['stage'] == 'layer3.assembly_admission')
        self.assertTrue(warm_admission['cacheHit'])
        observations = [e['metrics'] for e in warm_events if e.get('event') == 'workload'
                        and e.get('stage') == 'layer3.unit_validation_completed']
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(row['fullDecodePassed'] and row['validationElapsedSeconds'] > 0 for row in observations))
        self.assertEqual([row['audioSha256'] for row in observations], audio_hashes)
        self.assertTrue(any(e.get('stage') == 'layer3.cached_manifest' for e in warm_events))

    def test_ledger_mode_counts_real_decode_and_manifest_work_as_leaves(self):
        ledger = self.root.parent / 'progress.json'
        progress.save(ledger, progress.new_ledger('fixture', ['ko']))
        spans = []
        original_decode = renderer.integrity.probe_full_decode
        original_write = renderer.write_json_atomic
        def decode(*args, **kwargs):
            spans.append(accounting._span.get())
            return original_decode(*args, **kwargs)
        def write(path, value):
            if path.name == 'render-manifest.json':
                time.sleep(.02)
            return original_write(path, value)
        with patch.object(renderer.integrity, 'probe_full_decode', side_effect=decode), \
             patch.object(renderer, 'write_json_atomic', side_effect=write):
            self.render(ledger)
        events, report = self.report(ledger.parent / 'accounting')
        starts = {e['spanId']: e for e in events if e['event'] == 'stage_started'}
        parents = {e['parentSpanId'] for e in starts.values()}
        self.assertTrue(spans)
        self.assertTrue(all(span not in parents for span in spans))
        manifest = next(row for row in report['workUnits'] if row['stage'] == 'layer3.manifest_commit')
        self.assertGreaterEqual(manifest['elapsedSeconds'], .02)
        audit = measure.timing_audit(progress.load(ledger), events)['rows']
        step = next(row for row in audit if row['step'] == 'L3-02@ko')
        self.assertEqual(next(s for s in step['subStages'] if s['id'] == 'schedule_sync')['completedUnits'], 1)

    def test_unit_completion_is_not_exported_when_receipt_logging_fails(self):
        completed = []
        original_emit = accounting._emit
        def fail(event):
            if event['event'] == 'stage_finished' and event.get('stage') == 'layer3.receipt.ko.0000':
                raise accounting.AccountingWriteError('fixture')
            return original_emit(event)
        with accounting.accounting_session(self.root / 'accounting', 'fixture'), \
             patch.object(accounting, '_emit', side_effect=fail):
            with self.assertRaises(accounting.AccountingWriteError):
                renderer.render_units(self.context, self.paths, self.root, self.root / 'checkpoint-map.json',
                    synth_factory=fixtures.FakeSynth, completion_spans=completed)
        self.assertEqual(completed, [])
        self.assertEqual(len(fixtures.FakeSynth.calls), 1)
        # A deliberate later resume validates the known durable first unit;
        # only the as-yet unstarted second unit needs synthesis.
        self.f.render_units()
        self.assertEqual(len(fixtures.FakeSynth.calls), 2)

    def test_manifest_completion_requires_finished_log_and_resume_reuses_audio(self):
        rows = self.f.render_units()
        completed = []
        original_emit = accounting._emit
        def fail(event):
            if event['event'] == 'stage_finished' and event.get('stage') == 'layer3.manifest_commit':
                raise accounting.AccountingWriteError('fixture')
            return original_emit(event)
        with accounting.accounting_session(self.root / 'accounting', 'fixture'), \
             patch.object(accounting, '_emit', side_effect=fail):
            with self.assertRaises(accounting.AccountingWriteError):
                renderer.assemble(self.context, self.paths, self.root, rows, completion_spans=completed)
        self.assertEqual(completed, [])
        stored = (self.root / 'render-manifest.json').read_bytes()
        manifest = renderer.assemble(self.context, self.paths, self.root, rows, completion_spans=completed)
        self.assertEqual(len(completed), 1)
        self.assertEqual(stored, (self.root / 'render-manifest.json').read_bytes())
        self.assertEqual(manifest, json.loads(stored))
        self.assertEqual(len(fixtures.FakeSynth.calls), 2)

    def test_overflow_retains_legacy_metrics_and_blocks_track_commit(self):
        ledger = self.root.parent / 'progress.json'
        progress.save(ledger, progress.new_ledger('fixture', ['ko']))
        with measure.producer_step(ledger, 'L3-02@ko', locale='ko'):
            rows = self.f.render_units()
        with self.assertRaisesRegex(ValueError, 'exceeds 1x'), \
             measure.producer_step(ledger, 'L3-02@ko', locale='ko'):
            renderer.assemble(self.context, self.paths, self.root, rows,
                policy={'reactionLagSeconds': 100., 'interUtteranceGapSeconds': .05, 'maxEndLagSeconds': 8.})
        self.assertFalse((self.root / 'render-manifest.json').exists())
        events, _ = accounting.read_events(ledger.parent / 'accounting')
        metrics = [e['metrics'] for e in events if e['event'] == 'workload'
                   and e['stage'].endswith('.sub.schedule_sync')]
        self.assertTrue(metrics)
        self.assertGreater(metrics[-1]['overLimitUnits'], 0)
        failed = [e for e in events if e['event'] == 'stage_finished'
                  and e['stage'] == 'layer3.schedule_rejection']
        self.assertEqual(failed[-1]['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
