import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import sermon_accounting as accounting


class ObservabilityTests(unittest.TestCase):
    def test_request_identity_does_not_include_prompt_or_secret(self):
        data = accounting.request_metadata({'model': 'gpt-6-astra', 'reasoning': {'effort': 'medium'}, 'messages': [{'content': 'private sermon text'}], 'api_key': 'private-key'})
        self.assertEqual(data['reasoning_effort'], 'medium')
        self.assertEqual(len(data['requestPayloadSha256']), 64)
        self.assertNotIn('private', json.dumps(data))

    def test_snapshot_has_explicit_resource_scope_and_current_code_hash(self):
        identity = accounting.execution_identity()
        self.assertIn('scripts/sermon_accounting.py', identity['loadedProjectCodeSha256'])
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
                accounting.record_workload('render', {'inputUnits': 119, 'actualModelInputs': None, 'cookie': 'private-key'})
            d = accounting.summarize(work/'accounting')
            run = d['runs'][0]
            self.assertEqual(run['workloads'][0]['metrics']['inputUnits'],119)
            self.assertNotIn('cookie', run['workloads'][0]['metrics'])
            self.assertIsNotNone(run['workflows'][0]['executionIdentity'])
            self.assertTrue(run['workflows'][0]['evidenceAfter']['artifacts'])
            self.assertNotIn('private-key', (work/'accounting/events.jsonl').read_text())

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
            self.assertEqual(d['schemaVersion'],'sermon-workflow-accounting-v2')
            self.assertEqual(d['runs'][0]['workflows'],[])
            self.assertNotIn('wallSeconds',d['runs'][0])
            self.assertEqual(json.loads((Path(t)/'events.jsonl').read_text())['schemaVersion'],'sermon-workflow-accounting-v1')


if __name__=='__main__': unittest.main()
