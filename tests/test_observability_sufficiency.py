"""Logs must answer bounded questions without turning missing work into zero."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from scripts import sermon_accounting as accounting
from scripts import sermon_cache_observation as cache
from scripts import sermon_workflow_evidence as evidence
from scripts import weekly_pipeline_report as weekly
from tests import test_weekly_pipeline_report as weekly_tests
from tests import test_accounting_receipt_conflicts as receipt_tests


class ObservabilitySufficiencyTests(unittest.TestCase):
    def fixture(self, cls):
        test = cls(); test.setUp(); self.addCleanup(test.doCleanups)
        return test

    def test_interrupted_model_is_unknown_and_completed_parallel_subtotal_is_not_wall(self):
        t = self.fixture(weekly_tests.WeeklyPipelineReportTests)
        run = t.result()['runs'][0]
        self.assertEqual(run['executorCoverage']['production_model']['completedSpanSubtotalSeconds'], 8)
        self.assertEqual(run['executorCoverage']['human']['status'], 'not_observed')
        self.assertIsNone(run['executorCoverage']['human']['totalExecutionSeconds'])
        t.rows = [e for e in t.rows if not (e['event'] == 'stage_finished' and e['spanId'] == 'ko')]
        run = t.result()['runs'][0]
        self.assertEqual(run['status'], 'partial')
        self.assertEqual(run['executorCoverage']['production_model']['completedSpanSubtotalSeconds'], 3)
        self.assertEqual(run['executorCoverage']['production_model']['unfinishedSpanCount'], 1)
        self.assertIsNone(run['executorCoverage']['production_model']['totalExecutionSeconds'])
        self.assertIsNone(run['unfinishedSpans'][0]['elapsedSeconds'])
        self.assertIsNone(run['criticalPath'])
        self.assertIsNone(run['orchestrationOverheadSeconds'])

    def test_edges_timestamps_and_missing_queue_survive_projection(self):
        t = self.fixture(weekly_tests.WeeklyPipelineReportTests)
        run = t.result()['runs'][0]
        join = next(n for n in run['workUnits'] if n['stage'] == 'join')
        self.assertEqual(join['dependsOnSha256'], list(map(weekly.digest, ['ko', 'zh'])))
        self.assertTrue(join['startedAt']); self.assertTrue(join['finishedAt'])
        self.assertEqual(join['queueTimingStatus'], 'missing_instrumentation')
        self.assertIsNone(join['queueWaitSeconds'])
        self.assertIn('not_complete_telemetry', run['observabilityCoverage']['statusMeaning'])

    def test_all_readers_share_model_cost_latency_usage_and_requested_model_conflicts(self):
        t = self.fixture(receipt_tests.ReceiptConflictTests)
        variants = [{'model': 'gpt-6-sol'}, {'requestedModel': 'other-model'},
                    {'cost': {**t.api['cost'], 'estimatedUsd': 999}}, {'elapsedSeconds': 999},
                    {'usage': {**t.api['usage'], 'inputTokens': 5}}]
        for variant in variants:
            for reverse in (False, True):
                rows = [*t.events, t.duplicate(**variant)]
                if reverse: rows.reverse()
                summary = t.summarize(rows)
                report = weekly.project(t.root)
                self.assertEqual(report['receiptIntegrity'], summary['receiptIntegrity'])
                self.assertEqual(report['receiptIntegrity']['status'], 'conflicted')
                self.assertEqual(report['runs'][0]['usage']['status'], 'conflicted')
                self.assertIsNone(report['runs'][0]['usage']['byExecutor']['production_model']['calls'])

    def test_global_equivalent_and_conflicting_imports_share_attribution(self):
        t = self.fixture(receipt_tests.ReceiptConflictTests)
        stage = copy.deepcopy(next(e for e in t.events if e['event'] == 'stage_started' and e.get('stage') == 'translation'))
        stage.update(runId='imported-run', eventId='imported-stage', spanId='imported-span')
        other = t.duplicate(runId='imported-run', spanId='imported-span')
        for changed in (False, True):
            duplicate = copy.deepcopy(other)
            if changed: duplicate['model'] = 'other-model'
            for rows in ([*t.events, stage, duplicate], [stage, duplicate, *t.events]):
                summary = t.summarize(rows); report = weekly.project(t.root)
                self.assertEqual(report['receiptIntegrity'], summary['receiptIntegrity'])
                if changed:
                    self.assertTrue(all(r['usage']['status'] == 'conflicted' for r in report['runs']))
                else:
                    self.assertEqual(sum(len(r['usage']['directReceipts']) for r in report['runs']), 1)
                    self.assertEqual(report['receiptIntegrity']['equivalentDuplicatesIgnored'], 1)

    def test_sdk_import_model_and_latency_conflicts_are_aligned(self):
        t = self.fixture(receipt_tests.ReceiptConflictTests)
        with accounting.accounting_session(t.root/'sdk', 'sdk-test'):
            with accounting.stage('agent', executor_type='decision_agent'):
                accounting._emit({'event': 'sdk_call_finished', 'invocationId': 'invocation', 'status': 'completed',
                    'model': 'model-a', 'elapsedSeconds': 1.0,
                    'measurementScope': 'sdk_call_aggregate',
                    'usage': {'requests': 1, 'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5}})
        rows, damaged = accounting.read_events(t.root/'sdk'); self.assertFalse(damaged)
        api = next(e for e in rows if e['event'] == 'sdk_call_finished')
        for update in ({}, {'model': 'model-b'}, {'elapsedSeconds': 2.0}):
            copied = {**api, 'eventId': 'copy', **update}
            t.write([*rows, copied])
            summary = accounting.summarize(t.root); report = weekly.project(t.root)
            self.assertEqual(report['receiptIntegrity'], summary['receiptIntegrity'])
            self.assertEqual(report['receiptIntegrity']['status'], 'conflicted' if update else 'consistent')

    def test_canonical_l2_snapshot_has_required_and_optional_artifacts_without_legacy_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = {'englishSourcePackageJsonSha256': 'a'*64, 'translationPolicySha256': 'b'*64,
                'anchorManifestSha256': 'c'*64, 'sourceUnits': [{'english': 'PRIVATE CONTENT'}],
                'generation': {'translator': {'model': 'gpt-6-astra', 'requestIds': ['PRIVATE RESPONSE']}},
                'privateKey': 'SECRET', 'path': '/private/machine'}
            for name in ('request', 'run-identity', 'evidence', 'candidate', 'language-review'):
                (root/(name+'.json')).write_text(json.dumps(data))
            result = evidence.collect_workflow_evidence(root, 'canonical_layer2')
            self.assertEqual(result['missingCategories'], [])
            self.assertEqual(len(result['artifacts']), 5)
            self.assertFalse(result['currentRunExecutionProven'])
            self.assertEqual(result['artifacts'][0]['summary']['translationPolicySha256'], 'b'*64)
            for value in ('PRIVATE CONTENT', 'PRIVATE RESPONSE', 'SECRET', '/private/machine'):
                self.assertNotIn(value, json.dumps(result))
            (root/'candidate.json').unlink()
            self.assertEqual(evidence.collect_workflow_evidence(root, 'layer2_models')['missingCategories'], [])

    def test_cache_history_is_bound_safe_deduplicated_and_not_current_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root/'cache.json'
            saved = {'model': 'gpt-6-astra', 'requestId': 'PRIVATE_RESPONSE', 'payloadSha256': 'a'*64,
                     'result': {'content': 'PRIVATE CONTENT'}}
            output.write_text(json.dumps(saved))
            output.with_suffix('.raw.json').write_text(json.dumps({'payloadSha256': 'a'*64,
                'response': {'id': 'PRIVATE_RESPONSE', 'model': 'gpt-6-astra',
                'usage': {'prompt_tokens': 100, 'completion_tokens': 20}, 'choices': ['PRIVATE CONTENT']}}))
            with accounting.accounting_session(root/'accounting', 'cache-test'):
                with accounting.stage('cache_validation', depends_on=[], cache_hit=True):
                    for _ in range(2): cache.record('translator', saved, output, mode='validated_cache')
            report = weekly.project(root/'accounting'); run = report['runs'][0]
            self.assertEqual(run['historicalCacheUsage']['observations'], 2)
            self.assertEqual(run['historicalCacheUsage']['distinctHistoricalResponses'], 1)
            self.assertEqual(run['historicalCacheUsage']['knownHistoricalTokenSubtotal']['inputTokens'], 100)
            self.assertEqual(run['usage']['directReceipts'], [])
            self.assertIsNone(run['historicalCacheUsage']['historicalCostUsd'])
            self.assertEqual(run['cacheObservations'][0]['responseIdSha256'], hashlib.sha256(b'PRIVATE_RESPONSE').hexdigest())
            for private in ('PRIVATE_RESPONSE', 'PRIVATE CONTENT', tmp):
                self.assertNotIn(private, (root/'accounting/events.jsonl').read_text())
            self.assertIn('gpt-6-astra', weekly.markdown(report))
            # Missing or mismatched raw receipts cannot manufacture token zero.
            for raw in (None, {'payloadSha256': 'b'*64, 'response': {'usage': {'prompt_tokens': 999}}}):
                path = output.with_suffix('.raw.json')
                if raw is None: path.unlink()
                else: path.write_text(json.dumps(raw))
                with mock.patch.object(accounting, '_emit') as emit:
                    cache.record('translator', saved, output, mode='validated_cache')
                fields = emit.call_args[0][0]['fields']
                self.assertIsNone(fields['usage']['inputTokens'])
                self.assertNotEqual(fields['usageProvenance'], 'historical_bound_provider_receipt')

    def test_cache_reader_rejects_private_or_invalid_extensions(self):
        with self.assertRaises(ValueError): cache.safe_observation({'schemaVersion': cache.SCHEMA, 'prompt': 'private'})

    def test_cache_logging_failure_does_not_repeat_transport_or_rewrite_outputs(self):
        from tests import test_run_target_language_models as fixtures
        from scripts import run_target_language_models as runner
        t = self.fixture(fixtures.RunTargetLanguageModelsTests); f = t.fixture
        result = runner.run(f.source, f.anchor, f.policy, t.out, 'fixture-key', t.fake_call)
        before = {p.name: p.read_bytes() for p in t.out.glob('*.json')}
        t.calls.clear()
        emit = accounting._emit
        def fail(event):
            if event.get('code') == cache.CODE: raise accounting.AccountingWriteError('injected_cache_log_failure')
            return emit(event)
        with mock.patch.object(accounting, '_emit', side_effect=fail):
            with self.assertRaises(accounting.AccountingWriteError):
                runner.run(f.source, f.anchor, f.policy, t.out, 'fixture-key', t.fake_call)
        self.assertEqual(t.calls, [])
        self.assertEqual({p.name: p.read_bytes() for p in t.out.glob('*.json')}, before)
        self.assertEqual(runner.run(f.source, f.anchor, f.policy, t.out, 'fixture-key', t.fake_call), result)
        self.assertEqual(t.calls, [])

    def test_safe_export_reprojects_without_paths_or_error_text(self):
        from scripts import export_observability_trace as exporter
        t = self.fixture(weekly_tests.WeeklyPipelineReportTests)
        for row in t.rows:
            row.update(pid=123, thread='private-thread', error={'message': 'SECRET CONTENT'})
        t.result()
        result = exporter.export(t.root, t.root/'export')
        exported = t.root/'export'
        self.assertEqual(result['sourceEventCount'], len(t.rows))
        self.assertEqual(weekly.project(exported)['status'], 'projected')
        text = (exported/'events.jsonl').read_text()
        for private in ('private-thread', 'SECRET CONTENT', '"pid"'):
            self.assertNotIn(private, text)

    def test_completed_parent_with_interrupted_child_does_not_become_leaf_compute(self):
        t = self.fixture(weekly_tests.WeeklyPipelineReportTests)
        t.rows = []
        t.event('run_started', 0, workflow='test')
        t.stage('container', 0, 8, [])
        t.stage('child', 1, 7, [], 'production_model', parentSpanId='container')
        t.rows = [e for e in t.rows if not (e.get('spanId') == 'child' and e['event'] == 'stage_finished')]
        t.event('run_finished', 8, workflow='test', status='failed')
        run = t.result()['runs'][0]
        self.assertEqual(run['workUnits'], [])
        self.assertEqual(run['executorCoverage']['production_model']['unfinishedSpanCount'], 1)
        self.assertIsNone(run['executorCoverage']['production_model']['totalExecutionSeconds'])
        self.assertEqual(run['status'], 'partial')

    def test_local_model_identity_keeps_provider_usage_not_applicable(self):
        from scripts import sermon_local_model_observation as local
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with accounting.accounting_session(root, 'local-test'):
                with accounting.stage('local_asr', executor_type='production_model', depends_on=[]):
                    local.record('mlx-community/whisper-model', 'a'*64, 'b'*64, status='started')
                    local.record('mlx-community/whisper-model', 'a'*64, 'b'*64, status='completed', output_sha256='c'*64, elapsed_seconds=0.01)
            report = weekly.project(root)['runs'][0]
            self.assertEqual(len(report['localModelObservations']), 2)
            self.assertTrue(all(o['providerTokens'] is None for o in report['localModelObservations']))
            self.assertEqual(next(n for n in report['workUnits'] if n['stage'] == 'local_asr')['models'], ['mlx-community/whisper-model'])
            with self.assertRaises(ValueError): local.record('/private/path', 'a'*64, 'b'*64, status='started')

    def test_plugin_rejection_has_safe_reason_and_keeps_original_error(self):
        from scripts import run_target_language_models as runner
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with accounting.accounting_session(root, 'binding-test'):
                with mock.patch.object(runner.producer, 'plugin_implementation_sha256', return_value='b'*64):
                    with self.assertRaisesRegex(ValueError, 'Language plugin implementation'):
                        runner.require_plugin_identity(Path('unused'), 'a'*64)
            events, bad = accounting.read_events(root); self.assertFalse(bad)
            reason = next(e for e in events if e.get('code') == 'layer2_admission_rejected')
            self.assertEqual(reason['fields']['reasonCode'], 'plugin_implementation_mismatch')
            with mock.patch.object(runner.producer, 'plugin_implementation_sha256', return_value='b'*64), mock.patch.object(accounting, 'record_workload', side_effect=accounting.AccountingWriteError('injected')):
                with self.assertRaisesRegex(ValueError, 'Language plugin implementation'):
                    runner.require_plugin_identity(Path('unused'), 'a'*64)
