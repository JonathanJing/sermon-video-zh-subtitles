import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.sermon_accounting import SCHEMA
from scripts.weekly_pipeline_report import digest, markdown, project


class WeeklyPipelineReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rows = []
        self.event('run_started', 0, workflow='test')
        self.stage('source', 0, 2, [])
        self.stage('ko', 2, 7, ['source'], 'production_model')
        self.stage('zh', 2, 5, ['source'], 'production_model')
        self.stage('join', 7, 8, ['ko', 'zh'])
        self.event('run_finished', 8, workflow='test', status='completed')

    def event(self, event, time, **fields):
        row = dict(schemaVersion=SCHEMA, runId='run', eventId=str(len(self.rows)),
                   event=event, recordedAt=f'2026-09-30T00:00:{time:02d}+00:00', **fields)
        self.rows.append(row)
        return row

    def stage(self, ident, begin, end, deps, executor='deterministic_program', **fields):
        base = dict(stage=ident, spanId=ident, executorType=executor, dependsOn=deps,
                    workUnitId=ident, attemptId=ident, **fields)
        self.event('stage_started', begin, startedAt=f'2026-09-30T00:00:{begin:02d}+00:00', **base)
        self.event('stage_finished', end, elapsedSeconds=end-begin, status='completed',
                   cacheHit=False, billing='local', **base)

    def result(self):
        source = self.root / 'events.jsonl'
        data = ''.join(json.dumps(row) + '\n' for row in self.rows)
        source.write_text(data)
        result = project(self.root)
        self.assertEqual(source.read_text(), data)
        return result

    def test_parallel_convergence_critical_path_slack_and_markdown(self):
        report = self.result()
        run = report['runs'][0]
        self.assertEqual(report['status'], 'projected')
        self.assertEqual(run['endToEndWallSeconds'], 8)
        cp = run['criticalPath']
        self.assertEqual(cp['activeSeconds'], 8)
        self.assertEqual(cp['spanPath'], list(map(digest, ['source', 'ko', 'join'])))
        self.assertEqual(cp['branchSlackSeconds'][digest('zh')], 2)
        self.assertEqual(run['leafElapsedByExecutor']['production_model'], 8)
        self.assertIn('Active critical-path seconds: 8', markdown(report))
        self.assertIsNone(run['pageReadyAt'])
        self.assertEqual(run['acceptance'], 'not_evaluated')

    def test_invalid_graphs_do_not_claim_critical_path(self):
        baseline = copy.deepcopy(self.rows)
        for deps, code in [(['missing'], 'missing_or_container_dependency'),
                           (['join'], 'dependency_cycle'), (['ko'], 'dependency_interval_overlap')]:
            with self.subTest(code=code):
                self.rows = copy.deepcopy(baseline)
                for row in self.rows:
                    if row.get('spanId') == 'source':
                        row['dependsOn'] = deps
                run = self.result()['runs'][0]
                self.assertIsNone(run['criticalPath'])
                self.assertIn(code, run['diagnostics'])

    def test_legacy_unfinished_and_negative_times_remain_partial(self):
        baseline = copy.deepcopy(self.rows)
        for change, code in [('legacy', 'legacy_dependency_or_executor_unknown'),
                             ('unfinished', 'unfinished_or_ambiguous_span'), ('negative', 'invalid_interval')]:
            self.rows = copy.deepcopy(baseline)
            if change == 'legacy':
                for row in self.rows:
                    row['schemaVersion'] = 'sermon-workflow-accounting-v2'
                    row.pop('dependsOn', None); row.pop('executorType', None)
            elif change == 'unfinished':
                self.rows = [row for row in self.rows if not (row['event'] == 'stage_finished' and row['spanId'] == 'ko')]
            else:
                self.rows[2]['recordedAt'] = '2026-09-29T00:00:00+00:00'
            run = self.result()['runs'][0]
            self.assertIsNone(run['criticalPath'])
            self.assertIn(code, run['diagnostics'])

    def test_parent_wrappers_not_double_counted_and_waits_separate(self):
        self.rows = []
        self.event('run_started', 0, workflow='test')
        self.stage('wrapper', 0, 10, [])
        self.stage('source', 0, 2, [], parentSpanId='wrapper')
        self.stage('approval', 2, 8, ['source'], 'human', parentSpanId='wrapper')
        self.stage('done', 8, 10, ['approval'], parentSpanId='wrapper')
        self.event('run_finished', 10, workflow='test', status='completed')
        run = self.result()['runs'][0]
        self.assertEqual(run['criticalPath']['activeSeconds'], 4)
        self.assertEqual(run['leafElapsedByExecutor']['human'], 6)
        self.assertEqual(run['leafElapsedByExecutor']['deterministic_program'], 4)

    def test_usage_dedup_and_sdk_not_added_unknown_not_zero(self):
        usage = dict(inputTokens=100, cachedInputTokens=40, outputTokens=10, reasoningTokens=None, cacheWriteTokens=None)
        for attempt in ('a', 'b'):
            self.event('api_attempt', 7, spanId='ko', stage='ko', attemptId=attempt,
                       responseId='same-response', status='completed', usage=usage, cost={})
        self.event('sdk_call_finished', 7, invocationId='sdk', model='test', status='completed', usage={'input_tokens': 500, 'output_tokens': 50})
        self.event('api_attempt_started', 7, attemptId='unknown-outcome', stage='ko')
        usage = self.result()['runs'][0]['usage']
        self.assertEqual(len(usage['directReceipts']), 1)
        self.assertEqual(usage['byExecutor']['production_model']['knownSubtotal']['nonCachedInputTokens'], 60)
        self.assertEqual(usage['byExecutor']['production_model']['missingFields']['reasoningTokens'], 1)
        self.assertEqual(len(usage['sdkAggregates']), 1)
        self.assertIsNone(usage['combinedTokenTotal'])
        self.assertEqual(usage['unresolvedAttempts'], 1)

    def test_conflicting_receipts_are_order_independent_and_never_totalled(self):
        baseline = copy.deepcopy(self.rows)
        for kind in ('api_attempt', 'sdk_call_finished'):
            for field in ('usage', 'status', 'executor'):
                with self.subTest(kind=kind, field=field):
                    self.rows = copy.deepcopy(baseline)
                    if kind == 'api_attempt':
                        original = self.event(kind, 7, spanId='ko', stage='ko', responseId='same',
                                              status='completed', usage=dict(inputTokens=100, outputTokens=None, cachedInputTokens=None, cacheWriteTokens=None, reasoningTokens=None), cost={})
                    else:
                        original = self.event(kind, 7, spanId='ko', invocationId='same', model='test',
                                              status='completed', usage={'input_tokens': 100})
                    other = copy.deepcopy(original)
                    other['eventId'] = 'conflict'
                    if field == 'usage':
                        other['usage']['inputTokens' if kind == 'api_attempt' else 'input_tokens'] = 200
                    elif field == 'status':
                        other['status'] = 'failed'
                    else:
                        other['spanId'] = 'source'
                    self.rows.append(other)
                    first = self.result()['runs'][0]
                    self.rows.reverse()
                    second = self.result()['runs'][0]
                    self.assertEqual(first, second)
                    self.assertEqual(first['status'], 'partial')
                    self.assertIn('conflicting_usage_receipts', first['diagnostics'])
                    self.assertEqual(len(first['usage']['conflicts']), 1)
                    self.assertTrue(all(row['knownSubtotal']['inputTokens'] is None
                                        for row in first['usage']['byExecutor'].values()))

    def test_dependency_must_finish_before_ready_with_timestamp_tolerance(self):
        self.rows = []
        self.event('run_started', 0, workflow='test')
        self.stage('dep', 0, 5, [])
        self.stage('child', 6, 7, ['dep'], dependencyReadyAt='2026-09-30T00:00:02+00:00',
                   queuedAt='2026-09-30T00:00:03+00:00')
        self.event('run_finished', 7, workflow='test', status='completed')
        result = self.result()['runs'][0]
        self.assertEqual(result['status'], 'partial')
        self.assertIn('dependency_not_finished_at_ready', result['diagnostics'])
        child = next(n for n in result['workUnits'] if n['workUnitId'] == 'child')
        self.assertEqual(child['dependencyReadyAt'], '2026-09-30T00:00:02+00:00')
        self.assertIsNone(child['queueWaitSeconds'])
        for row in self.rows:
            if row.get('spanId') == 'child':
                row['dependencyReadyAt'] = '2026-09-30T00:00:04.999+00:00'
                row['queuedAt'] = '2026-09-30T00:00:05+00:00'
        self.assertEqual(self.result()['status'], 'projected')

    def test_invalid_queue_and_parent_cycles_are_rejected(self):
        baseline = copy.deepcopy(self.rows)
        for key, value, code in [('queuedAt', '2026-09-30T00:00:09+00:00', 'invalid_interval'),
                                 ('parentSpanId', 'source', 'parent_cycle'),
                                 ('parentSpanId', 'missing', 'missing_parent')]:
            self.rows = copy.deepcopy(baseline)
            for row in self.rows:
                if row.get('spanId') == 'source':
                    row[key] = value
            run = self.result()['runs'][0]
            self.assertIsNone(run['criticalPath'])
            self.assertIn(code, run['diagnostics'])

    def test_failed_retry_attempts_are_distinct_nodes(self):
        self.rows = []
        self.event('run_started', 0, workflow='test')
        self.stage('attempt-one', 0, 2, [], 'production_model')
        self.rows[-1]['status'] = 'failed'
        self.stage('attempt-two', 2, 5, ['attempt-one'], 'production_model')
        self.event('run_finished', 5, workflow='test', status='completed')
        run = self.result()['runs'][0]
        self.assertEqual(run['criticalPath']['activeSeconds'], 5)
        self.assertEqual(len(run['workUnits']), 2)
        self.assertEqual(run['workUnits'][1]['status'], 'failed')

    def test_identical_reimport_is_idempotent_but_conflict_fails_closed(self):
        self.rows.append(dict(self.rows[1]))
        report = self.result()
        self.assertEqual(report['status'], 'projected')
        self.assertEqual(report['duplicateEventsIgnored'], 1)
        self.assertEqual(report['runs'][0]['criticalPath']['activeSeconds'], 8)
        self.rows[-1]['stage'] = 'different'
        report = self.result()
        self.assertEqual(report['status'], 'partial')
        self.assertIsNone(report['runs'][0]['criticalPath'])

    def test_duration_and_run_boundary_cannot_fabricate_measurements(self):
        self.rows[2]['elapsedSeconds'] = 100
        run = self.result()['runs'][0]
        self.assertIn('invalid_interval', run['diagnostics'])
        self.assertIsNone(run['criticalPath'])
        self.rows[2]['elapsedSeconds'] = 2
        self.rows[-1]['recordedAt'] = '2026-09-30T00:00:07+00:00'
        run = self.result()['runs'][0]
        self.assertIn('span_outside_run_interval', run['diagnostics'])
        self.assertIsNone(run['criticalPath'])

    def test_uninstrumented_dependency_is_unknown_not_an_independent_root(self):
        for row in self.rows:
            if row.get('spanId') == 'ko':
                row['dependsOn'] = None
        run = self.result()['runs'][0]
        self.assertIsNone(run['criticalPath'])
        self.assertIn('legacy_dependency_or_executor_unknown', run['diagnostics'])

    def test_identical_span_ids_in_distinct_runs_never_join(self):
        second = [dict(row, runId='second') for row in self.rows]
        self.rows += second
        result = self.result()
        self.assertEqual(len(result['runs']), 2)
        self.assertTrue(all(run['criticalPath']['activeSeconds'] == 8 for run in result['runs']))

    def test_cli_preserves_source_and_refuses_existing_output(self):
        self.result()
        original = (self.root / 'events.jsonl').read_bytes()
        command = [sys.executable, '-m', 'scripts.weekly_pipeline_report', '--accounting-dir',
                   str(self.root), '--out-dir', str(self.root / 'report')]
        p = subprocess.run(command, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((self.root / 'report/report.json').read_text())
        self.assertEqual((self.root / 'report/report.md').read_text(), markdown(data))
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual((self.root / 'events.jsonl').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
