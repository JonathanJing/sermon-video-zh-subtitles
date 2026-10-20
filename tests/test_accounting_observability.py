import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tongxing_production import path_aliases
from tongxing_production.observability import accounting as accounting_impl
from tongxing_production.observability import accounting
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.observability import profile as log_profile
from tongxing_production.observability import observability_trace as safe_export


class ObservabilityTests(unittest.TestCase):
    def test_snapshot_keeps_legacy_non_object_execution_identity(self):
        row = {'schemaVersion': accounting.SCHEMA,
               'event': 'workflow_started', 'eventId': 'a', 'runId': 'r',
               'recordedAt': '2026-10-17T00:00:00Z', 'workflow': 'w',
               'executionIdentity': ['legacy']}
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / 'events.jsonl').write_text(json.dumps(row) + '\n')
            events, damaged = accounting.read_events(temporary)
            from tongxing_production.observability import identity_sidecars as sidecars
            self.assertEqual(sidecars.collect(temporary, events), {})
            safe_export.export(Path(temporary), Path(temporary) / 'export')
        self.assertEqual(events, [row])
        self.assertEqual(damaged, [])

    def test_large_loaded_code_identity_uses_verified_private_sidecar(self):
        identity = accounting.execution_identity()
        modules = {f'scripts/synthetic_{i:04d}.py': f'{i:064x}' for i in range(800)}
        identity['loadedProjectCodeSha256'] = modules
        with tempfile.TemporaryDirectory() as temporary, patch.object(accounting_impl, 'execution_identity', return_value=identity):
            with log_profile.session(temporary, 'synthetic', work_kind='control', evidence_mode='synthetic'):
                pass
            rows, damaged = accounting.read_events(temporary)
            self.assertFalse(damaged)
            started = next(row for row in rows if row['event'] == 'workflow_started')
            self.assertEqual(started['contractVersion'], 'sermon-accounting-log-contract-v2')
            recorded = started['executionIdentity']
            self.assertEqual(recorded['loadedProjectCodeSha256'], {})
            digest = recorded['loadedProjectCodeManifestSha256']
            self.assertEqual(accounting_impl.load_execution_identity_sidecar(temporary, digest), modules)
            self.assertLessEqual(len(json.dumps(started, sort_keys=True, separators=(',', ':')).encode()) + 1, 64 * 1024)
            exported = Path(temporary) / 'safe-export'
            safe_export.export(Path(temporary), exported)
            self.assertEqual(accounting_impl.load_execution_identity_sidecar(exported, digest), modules)
            path = Path(temporary) / '.execution-identities' / (digest + '.json')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            # A branch briefly emitted this sidecar shape with the v1 marker.
            # Its reader may validate it, but must never change ledger bytes.
            transitional = Path(temporary) / 'transitional'
            transitional.mkdir()
            import shutil
            shutil.copytree(Path(temporary) / '.execution-identities',
                            transitional / '.execution-identities')
            legacy_rows = [{**row, 'contractVersion': 'sermon-accounting-log-contract-v1'}
                           for row in rows]
            from tongxing_production.observability import log_contract
            from tongxing_production.observability import outbox
            legacy_started = next(row for row in legacy_rows if row['event'] == 'workflow_started')
            self.assertFalse(log_contract.validator().is_valid(legacy_started))
            self.assertIs(log_contract.validate_event(legacy_started), legacy_started)
            with self.assertRaisesRegex(ValueError, 'transitional_version_new_write_rejected'):
                outbox.deliver(transitional / 'new-run', legacy_started)
            bound = transitional / 'bound-run'
            markers = bound / '.run-profiles'
            markers.mkdir(parents=True)
            marker = markers / (hashlib.sha256(legacy_started['runId'].encode()).hexdigest() + '.json')
            outbox.jobs._persist(marker, {'runId': legacy_started['runId'],
                                          'contractVersion': log_contract.LEGACY_VERSION})
            with self.assertRaisesRegex(ValueError, 'transitional_version_new_write_rejected'):
                outbox.deliver(bound, legacy_started)
            legacy_bytes = ''.join(json.dumps(row) + '\n' for row in legacy_rows).encode()
            (transitional / 'events.jsonl').write_bytes(legacy_bytes)
            recovered, damaged = accounting.read_events(transitional)
            self.assertFalse(damaged)
            self.assertEqual(recovered, legacy_rows)
            self.assertEqual((transitional / 'events.jsonl').read_bytes(), legacy_bytes)
            self.assertEqual(accounting.summarize(transitional)['eventIntegrity']['status'], 'consistent')
            path.chmod(0o644)
            _, damaged = accounting.read_events(temporary)
            self.assertEqual(len(damaged), 1)
            with self.assertRaisesRegex(ValueError, 'sidecar_permissions'):
                accounting_impl._bounded_event_identity(temporary, identity)
            path.chmod(0o600)
            self.assertEqual(accounting_impl._bounded_event_identity(temporary, identity)[
                'loadedProjectCodeManifestSha256'], digest)
            sidecar_bytes = path.read_bytes()
            path.write_text('[' * 10000 + '0' + ']' * 10000)
            _, damaged = accounting.read_events(temporary)
            self.assertEqual(len(damaged), 1)
            path.write_bytes(sidecar_bytes)
            ledger = Path(temporary) / 'events.jsonl'
            original = ledger.read_text()
            lines = [json.loads(line) for line in original.splitlines()]
            next(row for row in lines if row['event'] == 'workflow_started')['executionIdentity'][
                'loadedProjectCodeSha256'] = {'scripts/conflict.py': 'a' * 64}
            ledger.write_text(''.join(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n' for row in lines))
            _, damaged = accounting.read_events(temporary)
            self.assertEqual(len(damaged), 1)
            ledger.write_text(original)
            path.write_text('{}')
            with self.assertRaises(ValueError):
                accounting_impl.load_execution_identity_sidecar(temporary, digest)
            _, damaged = accounting.read_events(temporary)
            self.assertEqual(len(damaged), 1)
            with self.assertRaisesRegex(ValueError, 'damaged_source_ledger_requires_inspection'):
                safe_export.export(Path(temporary), Path(temporary) / 'rejected-export')

    def test_request_identity_does_not_include_prompt_or_secret(self):
        data = accounting.request_metadata({'model': 'gpt-6-astra', 'reasoning': {'effort': 'medium'}, 'messages': [{'content': 'private sermon text'}], 'api_key': 'private-key'})
        self.assertEqual(data['reasoning_effort'], 'medium')
        self.assertEqual(len(data['requestPayloadSha256']), 64)
        self.assertNotIn('private', json.dumps(data))

    def test_snapshot_has_explicit_resource_scope_and_current_code_hash(self):
        identity = accounting.execution_identity()
        # Keys name where each loaded module lives; the accounting module moved in I3.
        self.assertIn(path_aliases.resolve('scripts/sermon_accounting.py'), identity['loadedProjectCodeSha256'])
        with tempfile.TemporaryDirectory() as t:
            snap = accounting.resource_snapshot(t)
            self.assertGreater(snap['processPeakRssBytes'], 0)
            self.assertGreater(snap['diskFreeBytes'], 0)
            self.assertIsNone(snap['gpuPeakBytes'])
            self.assertIn('lifetime', snap['scope'])

    def test_workload_and_evidence_survive_summary(self):
        with tempfile.TemporaryDirectory() as t:
            work = Path(t)
            (work/'workflow-receipt.json').write_text(json.dumps({'status':'candidate_ready_for_extended_saturday_review','jobSha256':'a'*64,'humanAudioReview':'pending','command':'private-key'}))
            with accounting.accounting_session(work/'accounting', 'weekly_dubbing', {'jobSha256':'a'*64}):
                with accounting.orchestration('bookkeeping', depends_on=[]):
                    sum(range(100))
                accounting.record_workload('render', {'inputUnits': 119, 'actualModelInputs': None, 'cookie': 'private-key'})
            d = accounting.summarize(work/'accounting')
            run = d['runs'][0]
            self.assertEqual(len(run['workloads']), 1)
            self.assertEqual(run['workloads'][0]['stage'], 'render')
            self.assertEqual(run['workloads'][0]['metrics']['inputUnits'],119)
            self.assertNotIn('cookie', run['workloads'][0]['metrics'])
            self.assertIsNotNone(run['workflows'][0]['executionIdentity'])
            self.assertTrue(run['workflows'][0]['evidenceAfter']['artifacts'])
            self.assertNotIn('private-key', (work/'accounting/events.jsonl').read_text())
            raw = (work/'accounting/events.jsonl').read_bytes()
            events, damaged = accounting.read_events(work/'accounting')
            self.assertFalse(damaged)
            internal = {e['stage'] for e in events if e['event'] == 'workload'
                        and e['stage'] in accounting.INTERNAL_TIMING_WORKLOADS}
            self.assertEqual(internal, accounting.INTERNAL_TIMING_WORKLOADS)
            from tongxing_production.observability import weekly_projection as weekly
            projection = weekly.project(work/'accounting')['runs'][0]
            self.assertEqual([e['stage'] for e in projection['workloadEvidence']], ['render'])
            self.assertEqual(projection['workloadEvidence'][0]['metrics']['inputUnits'], 119)
            self.assertEqual(projection['telemetryEvidence']['queue']['localInlineDispatchCount'], 1)
            self.assertGreater(projection['orchestrationOverheadSeconds'], 0)
            self.assertEqual((work/'accounting/events.jsonl').read_bytes(), raw)

    def test_only_exact_internal_timing_stages_are_separated(self):
        with tempfile.TemporaryDirectory() as temporary:
            with accounting.accounting_session(temporary, 'test'):
                accounting.record_workload('timing.business', {'inputUnits': 7})
                accounting.record_workload('timing.inline_dispatch_v2', {'inputUnits': 8})
            workloads = accounting.summarize(temporary)['runs'][0]['workloads']
            self.assertEqual([e['stage'] for e in workloads], ['timing.business', 'timing.inline_dispatch_v2'])

    def test_latency_percentiles_and_duration_usage_coverage(self):
        with tempfile.TemporaryDirectory() as t:
            with accounting.accounting_session(t,'test'):
                with accounting.stage('asr', billing='api'):
                    for n,seconds in enumerate([1,2,3,4,10]):
                        accounting.record_api_attempt('gpt-transcribe', {'id':str(n),'usage':{'seconds':30}}, seconds)
                    accounting.record_api_attempt('gpt-transcribe', None, 2, 'failed','HTTPError',http_status=429)
            row = next(r for r in accounting.summarize(t)['stages'] if r['stage']=='asr')
            self.assertEqual(row['apiLatencySampleCount'],6)
            self.assertAlmostEqual(row['apiLatencyP50Seconds'],2.5)
            self.assertAlmostEqual(row['usageReceiptCoverage'],5/6)
            self.assertEqual(row['failedApiAttempts'],1)

    def test_separate_accounting_directory_observes_actual_source_run(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            source_run = root / 'source-run'
            with accounting.accounting_session(root / 'ledgers' / 'source-run', 'same_video_intake', evidence_directory=source_run):
                source_run.mkdir()
                (source_run / 'same-video-source.json').write_text(json.dumps({'schemaVersion':'sermon-same-video-source-v1','sourceId':'-fixture','sha256':'a'*64,'sameVersionConfirmed':True,'sermonOnly':True,'confirmationReference':'not for logging'}))
                (source_run / 'same-video-archive.json').write_text(json.dumps({'schemaVersion':'sermon-same-video-archive-v1','sourceVideoSha256':'a'*64,'humanWindow':'not_applicable'}))
            result = accounting.summarize(root / 'ledgers' / 'source-run')
            evidence = result['runs'][0]['workflows'][0]['evidenceAfter']
            self.assertEqual(evidence['missingCategories'], [])
            self.assertEqual(len(evidence['artifacts']), 2)
            source = next(item for item in evidence['artifacts'] if item['category'] == 'same_video_source')
            self.assertEqual(source['summary']['sourceId'], '-fixture')
            self.assertNotIn('not for logging', json.dumps(evidence))

    def test_v1_events_remain_readable_without_fabricated_metrics(self):
        with tempfile.TemporaryDirectory() as t:
            event = {'schemaVersion':'sermon-workflow-accounting-v1','eventId':'legacy','runId':'old','event':'run_started','workflow':'old','recordedAt':'2026-09-05T00:00:00+00:00'}
            (Path(t)/'events.jsonl').write_text(json.dumps(event)+'\n')
            d = accounting.summarize(t)
            self.assertEqual(d['schemaVersion'],'sermon-workflow-accounting-v3')
            self.assertEqual(d['runs'][0]['workflows'],[])
            self.assertNotIn('wallSeconds',d['runs'][0])
            self.assertEqual(json.loads((Path(t)/'events.jsonl').read_text())['schemaVersion'],'sermon-workflow-accounting-v1')

    def test_v3_stage_records_dependency_and_executor_identity(self):
        with tempfile.TemporaryDirectory() as t:
            with accounting.accounting_session(t, 'test'):
                with accounting.stage('translate', executor_type='production_model',
                        depends_on=['source-ready'], blocked_by=['human-review'],
                        work_unit_id='zh-CN.group-0001', attempt_id='attempt-2',
                        decision_id='decision-7', dependency_ready_at='2026-09-30T01:00:00+00:00',
                        queued_at='2026-09-30T01:00:01+00:00'):
                    pass
            rows = [json.loads(line) for line in (Path(t) / 'events.jsonl').read_text().splitlines()]
            event = next(row for row in rows if row['event'] == 'stage_started' and row['stage'] == 'translate')
            self.assertEqual(event['schemaVersion'], 'sermon-workflow-accounting-v3')
            self.assertEqual(event['executorType'], 'production_model')
            self.assertEqual(event['dependsOn'], ['source-ready'])
            self.assertEqual(event['blockedBy'], ['human-review'])
            self.assertEqual(event['workUnitId'], 'zh-CN.group-0001')
            self.assertEqual(event['attemptId'], 'attempt-2')
            self.assertEqual(event['decisionId'], 'decision-7')
            self.assertEqual(event['dependencyReadyAt'], '2026-09-30T01:00:00+00:00')
            self.assertNotIn('readyAt', event)

    def test_legacy_billing_and_explicit_executor_classification(self):
        with tempfile.TemporaryDirectory() as t:
            with accounting.accounting_session(t, 'test'):
                for billing in ('api', 'local', 'orchestrator', 'cloud', 'codex'):
                    with accounting.stage(billing, billing=billing):
                        pass
                for executor in accounting.EXECUTOR_TYPES:
                    with accounting.stage(executor, executor_type=executor):
                        pass
            rows, damaged = accounting.read_events(t)
            self.assertEqual(damaged, [])
            stages = [r for r in rows if r['event'] == 'stage_started']
            self.assertTrue(all(r['dependsOn'] is None for r in stages))
            actual = {r['stage']: r['executorType'] for r in stages}
            for billing, executor in {'api': 'production_model', 'codex': 'production_model',
                    'local': 'deterministic_program', 'orchestrator': 'deterministic_program',
                    'cloud': 'external_service'}.items():
                self.assertEqual(actual[billing], executor)
            for executor in accounting.EXECUTOR_TYPES:
                self.assertEqual(actual[executor], executor)

    def test_stage_yields_exact_attempt_span_for_downstream_dependencies(self):
        with tempfile.TemporaryDirectory() as t:
            with accounting.accounting_session(t, 'test'):
                with accounting.stage('source') as source_span:
                    self.assertIsInstance(source_span, str)
                with accounting.stage('downstream', depends_on=[source_span]):
                    pass
            events, damaged = accounting.read_events(t)
            row = next(e for e in events if e['event'] == 'stage_started' and e['stage'] == 'downstream')
            self.assertEqual(row['dependsOn'], [source_span])
            self.assertFalse(damaged)

    def test_stage_rejects_unbounded_or_unsafe_dependency_data(self):
        with self.assertRaises(ValueError):
            with accounting.stage('translate', depends_on=['contains private text']):
                pass
        with self.assertRaises(ValueError):
            with accounting.stage('translate', executor_type='shell_from_model'):
                pass


if __name__=='__main__': unittest.main()
