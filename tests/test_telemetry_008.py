"""Synthetic/local process evidence only: no model, provider or publication."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import shutil
import subprocess
import sys
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_dispatch_observation as dispatch
from scripts import sermon_log_profile as profile
from scripts import weekly_pipeline_report as report
from tests.test_weekly_pipeline_report import WeeklyPipelineReportTests
from tests.test_sermon_clock_handshake import ClockHandshakeTests


class DispatchObservationTests(unittest.TestCase):
    def test_cold_isolated_preload_then_actual_profile_stage_preserves_code_identity(self):
        overlay = Path(__file__).resolve().parents[1]
        repository = next(parent for parent in (overlay, *overlay.parents)
                          if (parent/'.git').exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracked = subprocess.check_output(['git', '-C', str(repository), 'ls-files',
                'scripts', 'schemas'], text=True).splitlines()
            for name in tracked:
                source = repository/name
                if source.is_file():
                    target = root/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            for source in (overlay/'scripts').glob('*.py'):
                if source.name != '__init__.py':
                    shutil.copy2(source, root/'scripts'/source.name)
            # Root/PD currently own uncommitted Source helper additions. Include
            # them as local code, but this probe never executes Source or a model.
            for name in ('sermon_source_failure.py', 'sermon_source_producer_compatibility.py'):
                if (repository/'scripts'/name).is_file():
                    shutil.copy2(repository/'scripts'/name, root/'scripts'/name)
            (root/'scripts/__init__.py').write_text('')
            code = '''
import sys,json,socket
from pathlib import Path
sys.path.insert(0,sys.argv[1])
def denied(*a,**k):raise AssertionError('network forbidden')
socket.socket.connect=denied
socket.create_connection=denied
from scripts import sermon_fresh_diagnostic as entry,sermon_accounting as accounting,sermon_log_profile as profile
entry.preload_execution_modules()
before=accounting.execution_identity()
assert 'scripts/sermon_dispatch_observation.py' in before['loadedProjectCodeSha256']
with profile.session(Path(sys.argv[1])/'actual-profile','cold.zero.call',work_kind='production',evidence_mode='synthetic'):
    with accounting.stage('cold.actual.leaf',depends_on=[]):sum(range(100))
after=accounting.execution_identity()
assert before==after,(set(after['loadedProjectCodeSha256'])-set(before['loadedProjectCodeSha256']))
print(json.dumps({'codeIdentityUnchanged':True,'providerCalls':0,'models':0,'dispatchHelperPreloaded':True}))
'''
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(root)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['dispatchHelperPreloaded'])

    def test_same_line_lambda_generator_error_keeps_business_failure_and_terminal_logs(self):
        import traceback
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = ValueError('private exception body must never be logged')
            captured = []
            real_location = accounting.error_location
            def capture_location(exc):
                captured.append([(Path(f.f_code.co_filename).resolve(), line, accounting._label(f.f_code.co_name))
                    for f, line in traceback.walk_tb(exc.__traceback__)])
                return real_location(exc)
            try:
                with patch.object(accounting, 'error_location', side_effect=capture_location), \
                        profile.session(root, 'lambda.failure', work_kind='production', evidence_mode='synthetic'):
                    with accounting.stage('lambda.actual.leaf', depends_on=[]):
                        (lambda: (_ for _ in ()).throw(original))()
            except ValueError as caught:
                self.assertIs(caught, original)
            else:
                self.fail('business exception was lost')
            self.assertFalse(getattr(original, 'sermon_logging_failed', False))
            frames = list(traceback.walk_tb(original.__traceback__))
            normalized = [(Path(f.f_code.co_filename).resolve(), line, accounting._label(f.f_code.co_name)) for f, line in frames]
            self.assertLess(len(set(normalized)), len(normalized), 'fixture must contain actual same-line normalized duplicates')
            rows, errors = accounting.read_events(root)
            self.assertFalse(errors)
            stage = next(e for e in rows if e['event'] == 'stage_finished' and e['stage'] == 'lambda.actual.leaf')
            run = next(e for e in rows if e['event'] == 'run_finished')
            self.assertEqual(stage['status'], 'failed')
            self.assertEqual(run['status'], 'failed')
            locations = stage['error']['frames']
            self.assertEqual(len(locations), len({(e['file'],e['line'],e['function']) for e in locations}))
            expected = []
            for file, line, function in captured[0]:
                try:
                    relative = file.relative_to(Path(accounting.__file__).resolve().parents[1])
                except ValueError:
                    continue
                item = {'file': str(relative), 'line': line, 'function': function}
                if item not in expected:
                    expected.append(item)
            self.assertEqual(locations, expected[-12:])
            self.assertNotIn(str(original), (root/'events.jsonl').read_text())

    def test_exact_process_run_terminal_witness_not_assumed_from_ids(self):
        scope = ('directory', 'run')
        dispatch._reset()
        ticks = iter(['ready', 'dispatch', 'unknown-dispatch', 'other-run-dispatch', 'other-process-dispatch'])
        now = lambda: next(ticks)
        dispatch.finished(scope, 'done')
        self.assertEqual(dispatch.observe(scope, ['done'], now), ('ready', 'dispatch'))
        self.assertEqual(dispatch.observe(scope, ['missing'], now), (None, 'unknown-dispatch'))
        self.assertEqual(dispatch.observe(('directory', 'other-run'), ['done'], now), (None, 'other-run-dispatch'))
        with patch.object(dispatch.os, 'getpid', return_value=99999999):
            self.assertEqual(dispatch.observe(scope, ['done'], now), (None, 'other-process-dispatch'))

    def test_actual_leaf_entry_records_dispatch_and_observed_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with profile.session(root, 'inline.test', work_kind='production', evidence_mode='synthetic'):
                with accounting.stage('source', depends_on=[]) as source:
                    sum(range(100))
                with accounting.stage('consumer', depends_on=[source]):
                    sum(range(100))
            rows, errors = accounting.read_events(root)
            self.assertFalse(errors)
            leaves = [e for e in rows if e['event'] == 'stage_started' and e['stage'] in ('source', 'consumer')]
            self.assertEqual(len(leaves), 2)
            self.assertTrue(all(e['dependencyReadyAt'] and e['queuedAt'] for e in leaves))
            run = report.project(root)['runs'][0]
            self.assertEqual(run['telemetryEvidence']['queue']['observedReadyAndDispatchCount'], 2)
            self.assertEqual(run['telemetryEvidence']['queue']['localInlineDispatchCount'], 2)
            self.assertEqual(run['telemetryEvidence']['queue']['resourceQueueStatus'], 'not_established')
            self.assertEqual(run['observabilityCoverage']['logCompleteness'], 'recorded_events_reconciled')

    def test_live_unfinished_dependency_and_legacy_caller_remain_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with profile.session(root, 'inline.test', work_kind='production', evidence_mode='synthetic'):
                with accounting.stage('unfinished', depends_on=[]) as unfinished:
                    with accounting.stage('premature', depends_on=[unfinished]):
                        pass
                with accounting.stage('legacy'):
                    pass
            rows, errors = accounting.read_events(root)
            self.assertFalse(errors)
            for row in rows:
                if row['event'] == 'stage_started' and row['stage'] in ('premature', 'legacy'):
                    self.assertIsNone(row['dependencyReadyAt'])
                    self.assertIsNotNone(row['queuedAt'])

    def test_failed_final_log_never_establishes_terminal_witness(self):
        scope = ('directory', 'run')
        dispatch._reset()
        token = accounting._identity.set(scope)
        original = accounting._emit
        seen = []
        def fail_final(event):
            if event['event'] == 'stage_started':
                seen.append(event['spanId'])
            if event['event'] == 'stage_finished':
                raise accounting.AccountingWriteError('terminal write failed')
            # No transport, filesystem or profile mock: this test isolates a
            # real stage's refusal to register a failed final write.
        try:
            with patch.object(accounting, '_emit', side_effect=fail_final):
                with self.assertRaises(accounting.AccountingWriteError):
                    with accounting.stage('unlogged', depends_on=[]):
                        pass
        finally:
            accounting._identity.reset(token)
        self.assertEqual(len(seen), 1)
        self.assertEqual(dispatch.observe(scope, seen, lambda: 'dispatch'), (None, 'dispatch'))



class TelemetryProjectionTests(WeeklyPipelineReportTests):
    # Reuse the established fixture graph; inherited core regressions also run.
    def clocks(self):
        for row in self.rows:
            if row['event'] not in {'stage_started', 'stage_finished'}:
                continue
            row['clockDomainId'] = 'a' * 32
            row['monotonicStartNs'] = str(int(report.seconds(row.get('startedAt', row['recordedAt'])) * 1e9))
        starts = {e['spanId']: e for e in self.rows if e['event'] == 'stage_started'}
        for row in self.rows:
            if row['event'] == 'stage_finished':
                row['monotonicStartNs'] = starts[row['spanId']]['monotonicStartNs']
                row['monotonicEndNs'] = str(int(row['monotonicStartNs']) + int(row['elapsedSeconds'] * 1e9))

    def test_old_uninstrumented_rows_are_not_retroactively_upgraded(self):
        run = self.result()['runs'][0]
        self.assertIsNone(run['pageReadyAt'])
        self.assertIsNone(run['orchestrationOverheadSeconds'])
        self.assertEqual(run['observabilityCoverage']['crossProcessCriticalPath'], 'not_established')
        self.assertEqual(run['telemetryEvidence']['queue']['observedReadyAndDispatchCount'], 0)
        self.assertEqual(run['observabilityCoverage']['logCompleteness'], 'not_established')

    def publication(self):
        self.rows = []
        self.event('run_started', 0, workflow='test')
        self.stage('diagnostic.dev_http', 1, 6, [])
        self.event('workload', 5, stage='diagnostic.dev_http_binding', spanId='diagnostic.dev_http',
                   metrics={'manifestSha256': 'a'*64, 'receiptSha256': 'b'*64, 'productionEligible': False})
        self.event('run_finished', 6, workflow='test', status='completed')

    def test_page_ready_requires_completed_hash_bound_http_observation(self):
        self.publication()
        run = self.result()['runs'][0]
        self.assertEqual(run['pageReadyAt'], '2026-09-30T00:00:05+00:00')
        self.assertEqual(run['acceptance'], 'not_evaluated')
        original = copy.deepcopy(self.rows)
        for variant in ('failed', 'outside', 'changed_binding'):
            self.rows = copy.deepcopy(original)
            if variant == 'failed':
                self.rows[2]['status'] = 'failed'
            elif variant == 'outside':
                self.rows[3]['recordedAt'] = '2026-09-30T00:00:09+00:00'
            else:
                self.event('workload', 5, stage='diagnostic.dev_http_binding', spanId='diagnostic.dev_http',
                           metrics={'manifestSha256': 'c'*64, 'receiptSha256': 'd'*64, 'productionEligible': False})
            self.assertIsNone(self.result()['runs'][0]['pageReadyAt'], variant)

    def test_damaged_ledger_cannot_claim_page_ready_or_reconciled_logs(self):
        self.publication()
        self.result()
        with (self.root/'events.jsonl').open('a') as stream:
            stream.write('{"partial":\n')
        run = report.project(self.root)['runs'][0]
        self.assertIsNone(run['pageReadyAt'])
        self.assertEqual(run['observabilityCoverage']['logCompleteness'], 'not_established')

    def overhead(self):
        self.rows = []
        self.event('run_started', 0, workflow='test')
        self.stage('orchestrator', 0, 10, [])
        self.stage('model', 1, 6, [], 'production_model', parentSpanId='orchestrator')
        self.stage('bookkeeping', 6, 9, [], parentSpanId='orchestrator')
        for span, t in (('orchestrator', 0), ('bookkeeping', 6)):
            self.event('workload', t, stage='timing.orchestration_v1', spanId=span,
                       metrics={'orchestrationWorkObserved': True})
        self.event('run_finished', 10, workflow='test', status='completed')
        self.clocks()

    def test_explicit_orchestration_union_excludes_producer_and_nested_double_count(self):
        self.overhead()
        run = self.result()['runs'][0]
        self.assertEqual(run['orchestrationOverheadSeconds'], 5)
        self.assertEqual(run['telemetryEvidence']['orchestrationSpanCount'], 2)
        self.assertIn('not_total_overhead', run['telemetryEvidence']['orchestrationScope'])

    def test_wrapper_gap_conflicting_marker_or_unproved_clock_never_becomes_overhead(self):
        self.overhead()
        original = copy.deepcopy(self.rows)
        self.rows = [e for e in original if e.get('stage') != 'timing.orchestration_v1']
        self.assertIsNone(self.result()['runs'][0]['orchestrationOverheadSeconds'])
        self.rows = copy.deepcopy(original)
        for span, t in (('orchestrator', 0), ('bookkeeping', 6)):
            self.event('workload', t, stage='timing.orchestration_v1', spanId=span,
                       metrics={'orchestrationWorkObserved': False})
        self.assertIsNone(self.result()['runs'][0]['orchestrationOverheadSeconds'])
        self.rows = copy.deepcopy(original)
        for e in self.rows:
            if e.get('spanId') == 'model':
                e['clockDomainId'] = 'b'*32
        self.assertIsNone(self.result()['runs'][0]['orchestrationOverheadSeconds'])


class HandshakeCoverageTests(ClockHandshakeTests):
    def test_real_handshake_projects_coverage_and_missing_join_stays_unknown(self):
        self.execute()
        run = report.project(self.root/'logs')['runs'][0]
        self.assertEqual(run['observabilityCoverage']['crossProcessCriticalPath'], 'verified_recorded_edges')
        self.assertGreater(run['telemetryEvidence']['cross']['verifiedCrossProcessEdges'], 0)
        # Separate directory/run, never fabricate a join for the earlier run.
        self.root = self.root/'missing-join'; self.root.mkdir()
        self.execute(join=False)
        run = report.project(self.root/'logs')['runs'][0]
        self.assertEqual(run['observabilityCoverage']['crossProcessCriticalPath'], 'not_established')


class ActualPreviewTelemetryTests(unittest.TestCase):
    def test_actual_preview_fixture_measures_bookkeeping_and_keeps_audio_gate(self):
        from tests import test_render_speculative_target_language_speech as fixtures
        f = fixtures.DiagnosticPreviewTests()
        f.setUp(); self.addCleanup(f.doCleanups)
        logs = f.f.root/'real-preview-telemetry'
        with profile.session(logs, 'preview.actual.fixture', work_kind='production', evidence_mode='synthetic'):
            result = f.render(predecessor_spans=[])
        run = report.project(logs)['runs'][0]
        self.assertEqual(run['status'], 'projected', run['diagnostics'])
        self.assertGreater(run['orchestrationOverheadSeconds'], 0)
        self.assertEqual(run['telemetryEvidence']['orchestrationSpanCount'], len(f.candidate['groups']))
        self.assertEqual(run['telemetryEvidence']['queue']['observedReadyAndDispatchCount'], len(run['workUnits']))
        self.assertEqual(result['status'], 'preview_only')
        self.assertEqual(len(fixtures.FakeSynth.calls), len(f.candidate['groups']))
        self.assertFalse(any(e['event'] == 'api_attempt' for e in accounting.read_events(logs)[0]))
